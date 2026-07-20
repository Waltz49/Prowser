#!/usr/bin/env python3
"""Subscribe thumbnail/list views to navigation index events."""

from PySide6.QtCore import QTimer

from event_bus import CURRENT_IMAGE_CHANGED, CURRENT_INDEX_CHANGED, VIEW_MODE_CHANGED


class ThumbnailHighlightSubscriber:
    """Apply canvas highlight and scroll in response to model navigation events."""

    def __init__(self, main_window):
        self.main_window = main_window
        self._last_applied_index = None
        bus = getattr(main_window, "event_bus", None)
        if bus:
            bus.subscribe(CURRENT_INDEX_CHANGED, self._on_current_index_changed)
            bus.subscribe(CURRENT_IMAGE_CHANGED, self._on_current_image_changed)
            bus.subscribe(VIEW_MODE_CHANGED, self._on_view_mode_changed)

    def apply_from_window_state(self, scroll: bool = True) -> None:
        """Apply highlight from window highlight_index (legacy callers without model events)."""
        index = getattr(self.main_window, "highlight_index", None)
        if index is None:
            return
        self._apply_highlight(index, scroll=scroll)

    def _on_current_index_changed(self, index: int) -> None:
        mw = self.main_window
        scroll = not getattr(mw, "browse_view_exit_in_progress", False)
        if getattr(mw, "browse_view_exit_in_progress", False):
            self._apply_highlight(index, scroll=False)
            if getattr(mw, "current_view_mode", None) != "list":
                QTimer.singleShot(100, mw.ensure_highlighted_visible)
            return
        self._apply_highlight(index, scroll=scroll)

    def _on_current_image_changed(self, image_path: str) -> None:
        if not image_path:
            return
        mw = self.main_window
        displayed = (
            mw.get_displayed_images()
            if hasattr(mw, "get_displayed_images")
            else getattr(mw, "displayed_images", [])
        )
        if not displayed or image_path not in displayed:
            return
        index = displayed.index(image_path)
        if index != self._last_applied_index:
            scroll = (
                getattr(mw, "current_view_mode", None) == "thumbnail"
                and not getattr(mw, "browse_view_exit_in_progress", False)
            )
            self._apply_highlight(index, scroll=scroll)

    def _on_view_mode_changed(self, mode: str) -> None:
        index = getattr(self.main_window, "highlight_index", 0)
        self._apply_highlight(index, scroll=False)

    def _apply_highlight(self, index: int, scroll: bool = True) -> None:
        mw = self.main_window
        view_mode = getattr(mw, "current_view_mode", "thumbnail")
        self._last_applied_index = index

        if view_mode == "list":
            container = getattr(mw, "list_view_container", None)
            if container and hasattr(container, "set_highlighted_index"):
                container.set_highlighted_index(index)
            return

        if view_mode in ("thumbnail", "browse"):
            container = getattr(mw, "thumbnail_container", None)
            if container and hasattr(container, "set_highlighted_index"):
                container.set_highlighted_index(index)
            if scroll and view_mode == "thumbnail":
                self._scroll_to_highlighted(index)

    def _scroll_to_highlighted(self, index: int) -> None:
        mw = self.main_window
        displayed = (
            mw.get_displayed_images()
            if hasattr(mw, "get_displayed_images")
            else getattr(mw, "displayed_images", [])
        )
        if not displayed or not (0 <= index < len(displayed)):
            return
        container = getattr(mw, "thumbnail_container", None)
        if not container:
            return
        get_rect = getattr(container, "get_thumbnail_rect", None)
        if get_rect and get_rect(index):
            canvas = getattr(container, "canvas", None)
            if canvas and hasattr(canvas, "scroll_to_highlighted"):
                canvas.scroll_to_highlighted()
            scroll_area = getattr(mw, "scroll_area", None)
            if scroll_area:
                scroll_area.viewport().update()
