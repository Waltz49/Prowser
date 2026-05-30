#!/usr/bin/env python3
"""
Thumbnail Context Menu Handler
Shows a context menu on macOS Control+click (not Cmd+click) over thumbnails (grid and list views).
Cmd+click is reserved for multiselect.
"""

# Standard library imports
import os
import shutil
import subprocess
from typing import Optional

# Third-party imports
from PySide6.QtCore import Qt
from PySide6.QtGui import QCursor, QKeySequence
from PySide6.QtWidgets import QLabel, QMenu, QVBoxLayout, QWidget, QWidgetAction

# Shortcut display format for menu labels (tab right-aligns)
def _shortcut_label(text: str, shortcut: str) -> str:
    if shortcut:
        native = QKeySequence(shortcut).toString(QKeySequence.SequenceFormat.NativeText)
        return f"{text}\t{native}"
    return text

# Local imports
from event_bus import THUMBNAIL_CLICKED
import thumbnail_constants as tc
from macos_process import reveal_in_finder
from utils import show_styled_warning


class MenuNoteLabel(QWidget):
    """Non-interactive menu item showing a note (e.g. multiselect hint). Similar to TextSeparator in Tools menu."""
    def __init__(self, text: str, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        label = QLabel(text)
        label.setStyleSheet(f"color: {tc.TEXT_DISABLED_HEX}; font-style: italic;")
        label.setWordWrap(True)
        layout.addWidget(label)


def _duplicate_file(path: str) -> Optional[str]:
    """Create a copy with *_copy.ext, preserving mtime/atime. Returns new path or None."""
    if not path or not os.path.isfile(path):
        return None
    base, ext = os.path.splitext(path)
    copy_path = f"{base}_copy{ext}"
    n = 1
    while os.path.exists(copy_path):
        copy_path = f"{base}_copy{n}{ext}"
        n += 1
    try:
        shutil.copy2(path, copy_path)
        return copy_path
    except OSError:
        return None


class ThumbnailContextMenuHandler:
    """
    Handles macOS Control+click context menu on thumbnails.
    Subscribes to THUMBNAIL_CLICKED and shows menu when macos_ctrl_pressed (MetaModifier).
    Cmd+click is used for multiselect.
    """

    def __init__(self, main_window):
        self.main_window = main_window
        if hasattr(main_window, 'event_bus') and main_window.event_bus:
            main_window.event_bus.subscribe(THUMBNAIL_CLICKED, self._on_thumbnail_clicked)

    def _on_thumbnail_clicked(self, index: int, cmd_pressed: bool, shift_pressed: bool, macos_ctrl_pressed: bool):
        """Handle THUMBNAIL_CLICKED - show context menu only when macOS Control+click (MetaModifier), not Cmd+click."""
        if not macos_ctrl_pressed:
            return
        self._show_context_menu(index)

    def _show_context_menu(self, clicked_index: int = -1):
        """Build and show the context menu at cursor position."""
        mw = self.main_window
        selected = getattr(mw, 'selected_files', set()) or set()
        selected_list = list(selected)
        multi_select = len(selected_list) > 1
        single_only = not multi_select

        # Use clicked index to get path when available; else fall back to current_image_path
        clicked_path = None
        if clicked_index >= 0 and hasattr(mw, 'displayed_images') and mw.displayed_images:
            if 0 <= clicked_index < len(mw.displayed_images):
                clicked_path = mw.displayed_images[clicked_index]
        if not clicked_path:
            clicked_path = getattr(mw, 'current_image_path', None)
        current_path = clicked_path

        if not current_path or not os.path.exists(current_path):
            return

        # If multiselect is active and the clicked image is not in the selection, do not show menu
        if multi_select and current_path not in selected:
            if hasattr(mw, 'status_notification') and mw.status_notification:
                mw.status_notification.show_message("Context menu request ignored.\nImage is not part of multiple selection.")
            return

        # Files to act on: selected if any, else current
        paths_to_act = selected_list if selected_list else [current_path]

        menu = QMenu(mw)
        menu.setStyleSheet(tc.QMENU_DEFAULT_STYLE_SHEET)

        # Rename (F2) - thumbnail view only
        in_thumbnail_view = getattr(mw, 'current_view_mode', None) == 'thumbnail'
        rename_action = menu.addAction(_shortcut_label("Rename", "F2"))
        rename_action.setShortcut(QKeySequence("F2"))
        rename_action.setEnabled(in_thumbnail_view)
        if in_thumbnail_view:
            rename_action.triggered.connect(self._start_rename)

        # Delete - respects confirm_delete setting; "Delete..." when confirmation will show
        confirm_delete = getattr(mw, 'confirm_delete', True)
        delete_label = "Delete..." if confirm_delete else "Delete"
        delete_action = menu.addAction(delete_label)
        delete_action.triggered.connect(
            lambda checked=False: self._delete_paths(paths_to_act)
        )

        # Copy pathname (⌘C) and copy image (⌃C) — same handlers as Edit menu
        copy_path_action = menu.addAction(_shortcut_label("Copy Pathname", "Ctrl+C"))
        copy_path_action.setShortcut(QKeySequence("Ctrl+C"))
        copy_path_action.triggered.connect(mw.copy_file_path_to_clipboard)

        copy_img_seq = QKeySequence(Qt.Key_C | Qt.MetaModifier)
        copy_image_action = menu.addAction(
            f"Copy image\t{copy_img_seq.toString(QKeySequence.SequenceFormat.NativeText)}"
        )
        copy_image_action.setShortcut(copy_img_seq)
        copy_image_action.setEnabled(single_only)
        if single_only:
            copy_image_action.triggered.connect(mw.copy_image_to_clipboard)

        # Duplicate - works for single or multi
        dup_action = menu.addAction("Duplicate")
        dup_action.triggered.connect(
            lambda checked=False: self._duplicate_selected(paths_to_act)
        )

        # Find Similar (⌘K)
        find_similar_action = menu.addAction(_shortcut_label("Find Similar Images...", "Ctrl+K"))
        find_similar_action.setShortcut(QKeySequence("Ctrl+K"))
        find_similar_action.triggered.connect(mw.reorder_images_by_similarity)

        # Show in directory (Shift+⌘H) - only in specific-files mode, single only
        specific_files = getattr(mw, 'specific_files_active', False)
        show_dir_action = menu.addAction(_shortcut_label("Show in Directory", "Ctrl+Shift+H"))
        show_dir_action.setShortcut(QKeySequence("Ctrl+Shift+H"))
        show_dir_action.setEnabled(single_only and specific_files)
        if single_only and specific_files:
            show_dir_action.triggered.connect(mw.show_image_in_directory)


        menu.addSeparator()

        # Edit in <editor> (⌘E) - single only
        from config import get_config
        settings = get_config().load_settings()
        editor_app = settings.get('image_editor_app', 'Preview')
        edit_action = menu.addAction(_shortcut_label(f"Edit in {editor_app}", "Ctrl+E"))
        edit_action.setShortcut(QKeySequence("Ctrl+E"))
        edit_action.setEnabled(single_only)
        if single_only:
            from external_editor import edit_current_image_with_editor
            edit_action.triggered.connect(
                lambda checked=False: edit_current_image_with_editor(mw)
            )

        # Edit EXIF user comment (Shift+⌘E)
        exif_action = menu.addAction(_shortcut_label("Edit EXIF User Comment...", "Ctrl+Shift+E"))
        exif_action.setShortcut(QKeySequence("Ctrl+Shift+E"))
        exif_action.triggered.connect(mw.edit_exif_usercomment)
        # Convert Format (⌘M)
        convert_action = menu.addAction(_shortcut_label("Convert Format...", "Ctrl+M"))
        convert_action.setShortcut(QKeySequence("Ctrl+M"))
        convert_action.triggered.connect(
            lambda checked=False: self._convert_format(paths_to_act)
        )

        # Extract faces — single only; shortcut shown for Tools > Debug (main window owns the QAction)
        extract_faces_action = menu.addAction(_shortcut_label("Extract Faces", "Ctrl+Shift+P"))
        extract_faces_action.setEnabled(single_only)
        if single_only:
            path = paths_to_act[0]
            extract_faces_action.triggered.connect(
                lambda checked=False, p=path: self._extract_faces(p)
            )

        # GPS (⌘G) - disable if no selected images have location data
        from map_manager import extract_gps_from_exif
        any_has_gps = any(extract_gps_from_exif(p) is not None for p in paths_to_act)
        gps_action = menu.addAction(_shortcut_label("Show Location on Map", "Ctrl+G"))
        gps_action.setShortcut(QKeySequence("Ctrl+G"))
        gps_action.setEnabled(any_has_gps)
        if any_has_gps:
            gps_action.triggered.connect(mw.open_map_for_current_image)

        if single_only:
            path = paths_to_act[0]
            from reference_graph import (
                has_resolvable_exif_references,
                open_reference_graph_for_path,
            )
            if has_resolvable_exif_references(path):
                show_ref_graph_action = menu.addAction("Show Reference Graph")
                show_ref_graph_action.triggered.connect(
                    lambda checked=False, p=path: open_reference_graph_for_path(mw, p)
                )

        find_refs_action = menu.addAction("Find References to This Image...")
        find_refs_action.setEnabled(single_only)
        if single_only:
            path = paths_to_act[0]
            find_refs_action.triggered.connect(
                lambda checked=False, p=path: self._find_references_in_other_images(p)
            )

        menu.addSeparator()

        # Open in Finder - single only
        open_finder_action = menu.addAction("Open in Finder")
        open_finder_action.setEnabled(single_only)
        if single_only:
            path = paths_to_act[0]
            open_finder_action.triggered.connect(
                lambda checked=False, p=path: self._open_in_finder(p)
            )

        # Set as wallpaper - submenu, single only
        wallpaper_menu = menu.addMenu("Set as Wallpaper")
        wallpaper_menu.setEnabled(single_only)
        if single_only:
            w_contain = wallpaper_menu.addAction("Fit (Contain)")
            w_contain.triggered.connect(
                lambda checked=False: mw.set_current_image_as_desktop_background('contain')
            )
            w_cover = wallpaper_menu.addAction("Fill (Cover)")
            w_cover.triggered.connect(
                lambda checked=False: mw.set_current_image_as_desktop_background('cover')
            )
            w_width = wallpaper_menu.addAction("Fit to Width")
            w_width.triggered.connect(
                lambda checked=False: mw.set_current_image_as_desktop_background('width')
            )
            w_height = wallpaper_menu.addAction("Fit to Height")
            w_height.triggered.connect(
                lambda checked=False: mw.set_current_image_as_desktop_background('height')
            )

        # Multiselect note at end - nonfunctional, explains why some items are disabled
        if multi_select:
            menu.addSeparator()
            note_action = QWidgetAction(mw)
            note_action.setDefaultWidget(MenuNoteLabel("Some Items Disabled Due to\nMultiple Selection"))
            menu.addAction(note_action)

        menu.exec(QCursor.pos())

    def _convert_format(self, paths: list):
        """Convert selected/current images to a different format."""
        from convert_format import convert_selected_images
        convert_selected_images(self.main_window, paths)

    def _find_references_in_other_images(self, path: str):
        """Scan folder EXIF comments for references to *path* and show results."""
        from find_references_dialog import find_and_show_references_dialog

        find_and_show_references_dialog(self.main_window, path)

    def _extract_faces(self, path: str):
        """Make image current, open settings on Faces tab, and trigger Examine current image."""
        mw = self.main_window
        if not path or not os.path.exists(path):
            return
        if hasattr(mw, 'set_current_image_by_path'):
            mw.set_current_image_by_path(path, fallback_index=0)
        if hasattr(mw, 'highlight_image'):
            mw.highlight_image()
        mw.show_settings(auto_extract_faces=True)

    def _start_rename(self):
        """Start inline rename for the highlighted thumbnail."""
        mw = self.main_window
        if not (getattr(mw, 'thumbnail_container', None) and hasattr(mw.thumbnail_container, 'canvas')):
            return
        canvas = mw.thumbnail_container.canvas
        index = getattr(mw, 'highlight_index', None)
        if index is None or not (0 <= index < len(canvas.thumbnails)):
            return
        canvas._start_inline_rename(index)

    def _open_in_finder(self, path: str):
        """Reveal file in Finder (macOS)."""
        try:
            reveal_in_finder(path)
        except subprocess.CalledProcessError:
            show_styled_warning(
                self.main_window,
                "Open in Finder",
                f"Failed to open {path} in Finder.",
            )
        except subprocess.TimeoutExpired:
            show_styled_warning(
                self.main_window,
                "Open in Finder",
                "Timeout while trying to open in Finder.",
            )
        except Exception as e:
            show_styled_warning(
                self.main_window,
                "Open in Finder",
                f"Unexpected error: {str(e)}",
            )

    def _duplicate_selected(self, paths: list):
        """Duplicate each selected file as *_copy.ext with same date."""
        created = []
        failed = []
        for path in paths:
            if not path or not os.path.isfile(path):
                continue
            new_path = _duplicate_file(path)
            if new_path:
                created.append(new_path)
            else:
                failed.append(path)

        if failed:
            show_styled_warning(
                self.main_window,
                "Duplicate",
                f"Failed to duplicate: {', '.join(os.path.basename(p) for p in failed)}",
            )
        if created:
            # Refresh display to show new files
            if hasattr(self.main_window, 'refresh_manager') and self.main_window.refresh_manager:
                self.main_window.refresh_manager.refresh_directory(force=True)

    def _delete_paths(self, paths: list):
        """Set selection to paths and invoke existing delete (respects confirm_delete)."""
        mw = self.main_window
        if not paths or not hasattr(mw, 'file_operations_manager') or not mw.file_operations_manager:
            return
        mw.selected_files = set(paths)
        mw._emit_selection_changed()
        mw.delete_selected_files()
