#!/usr/bin/env python3
"""Subscribe panes to CURRENT_IMAGE_CHANGED for navigation UI sync."""

import os

from event_bus import CURRENT_IMAGE_CHANGED


class NavigationUiSubscriber:
    """Update preview, title, and directory history on navigation (status bar/tree have own subscribers)."""

    def __init__(self, main_window):
        self.main_window = main_window
        bus = getattr(main_window, "event_bus", None)
        if bus:
            bus.subscribe(CURRENT_IMAGE_CHANGED, self._on_current_image_changed)

    def _on_current_image_changed(self, image_path: str) -> None:
        # Status bar and file tree have dedicated subscribers on CURRENT_IMAGE_CHANGED.
        self.apply_for_path(image_path, sync_status_bar=False, sync_tree=False)

    def apply_for_path(
        self,
        image_path: str,
        displayed=None,
        *,
        sync_status_bar: bool = True,
        sync_tree: bool = True,
    ) -> None:
        """Sync navigation UI for image_path (legacy highlight_image + event handler)."""
        if not image_path:
            return
        mw = self.main_window
        if displayed is None:
            displayed = (
                mw.get_displayed_images()
                if hasattr(mw, "get_displayed_images")
                else getattr(mw, "displayed_images", None)
            )
        if displayed and image_path:
            mw._current_highlighted_file_directory = os.path.dirname(image_path)

        if getattr(mw, "browse_view_exit_in_progress", False):
            self._update_preview_and_tree(image_path, sync_tree=sync_tree)
            return

        self._update_directory_history(image_path)
        if sync_status_bar:
            self._update_status_bar(image_path, displayed)
        if hasattr(mw, "update_preview_if_visible"):
            mw.update_preview_if_visible()
        if sync_tree:
            self._update_tree_highlight(image_path)
        self._update_window_title(image_path)

    def _update_directory_history(self, image_path: str) -> None:
        mw = self.main_window
        if getattr(mw, "specific_files_active", False):
            return
        current_dir = os.path.dirname(image_path)
        last_dir = getattr(mw, "_last_directory_in_history", None)
        if current_dir != last_dir:
            handler = getattr(mw, "directory_history_handler_for_menu", None)
            if handler:
                handler.add_directory(image_path)
            mw._last_directory_in_history = current_dir

    def _update_status_bar(self, image_path: str, displayed) -> None:
        mw = self.main_window
        if not hasattr(mw, "update_status_bar_current_image"):
            return
        last_updated = getattr(mw, "_last_status_bar_image_path", None)
        if last_updated != image_path:
            mw.update_status_bar_current_image(image_path, displayed)
            mw._last_status_bar_image_path = image_path

    def _update_preview_and_tree(self, image_path: str, *, sync_tree: bool = True) -> None:
        mw = self.main_window
        if hasattr(mw, "update_preview_if_visible"):
            mw.update_preview_if_visible()
        if sync_tree:
            self._update_tree_highlight(image_path)

    def _update_tree_highlight(self, image_path: str) -> None:
        mw = self.main_window
        if not image_path or getattr(mw, "current_view_mode", None) == "slideshow":
            return
        if (hasattr(mw, "_is_file_tree_showing") and mw._is_file_tree_showing() and
                hasattr(mw, "file_tree_handler") and mw.file_tree_handler.is_tree_initialized()):
            mw.file_tree_handler.highlight_current_file()

    def _update_window_title(self, image_path: str) -> None:
        mw = self.main_window
        idm = getattr(mw, "image_display_manager", None)
        if idm and hasattr(idm, "update_window_title_for_active_image"):
            idm.update_window_title_for_active_image()
        else:
            mw.setWindowTitle(f"Prowser - {image_path}")
