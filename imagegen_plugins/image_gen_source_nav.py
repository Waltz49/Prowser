#!/usr/bin/env python3
"""Prev/next source image controls for edit and expand dialogs."""

from __future__ import annotations

import os
from typing import Callable, Optional

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtWidgets import QHBoxLayout, QPushButton, QSizePolicy, QWidget

from theme.theme_service import get_active_theme
from utils import show_styled_critical, show_styled_warning


def _qobject_alive(obj) -> bool:
    if obj is None:
        return False
    try:
        from shiboken6 import isValid

        return isValid(obj)
    except ImportError:
        return True


def resolve_image_gen_main_window(dialog: QWidget):
    """Walk parent widgets to find the host main window."""
    from imagegen_plugins.image_gen_panel_shell import find_image_gen_unified_shell

    if getattr(dialog, "_panel_mode", False):
        shell = find_image_gen_unified_shell(dialog)
        if shell is not None:
            mw = getattr(shell, "_main_window", None)
            if mw is not None and hasattr(mw, "current_view_mode"):
                return mw
    widget = dialog
    while widget is not None:
        if hasattr(widget, "current_view_mode"):
            return widget
        host = getattr(widget, "_main_window", None)
        if host is not None and hasattr(host, "current_view_mode"):
            return host
        widget = widget.parent()
    return None


def active_image_path_for_browse_or_thumbnail(main_window) -> Optional[str]:
    """Active image in browse view or a single thumbnail selection."""
    if main_window is None:
        return None
    image_path = None
    if main_window.current_view_mode == "browse":
        if hasattr(main_window, "get_current_image_path"):
            image_path = main_window.get_current_image_path()
    elif main_window.current_view_mode == "thumbnail":
        if hasattr(main_window, "selection_manager") and main_window.selection_manager:
            selected_files = main_window.selection_manager.get_selected_files()
            if selected_files and len(selected_files) == 1:
                image_path = selected_files[0]
    if not image_path or not os.path.isfile(image_path):
        return None
    return image_path


def open_image_in_browse(main_window, file_path: str) -> None:
    """Open *file_path* in the main window browse view."""
    path = (file_path or "").strip()
    if not path or not os.path.isfile(path):
        show_styled_warning(
            main_window,
            "Invalid File",
            f"File does not exist: {path or '(unknown)'}",
        )
        return
    try:
        if hasattr(main_window, "set_date_sort"):
            main_window.set_date_sort(reverse=False, notify=False)
        loader = getattr(main_window, "load_file_with_directory_thumbnails", None)
        if loader is None:
            show_styled_warning(
                main_window,
                "Cannot open image",
                "Browse view is not available.",
            )
            return
        loader(path)
    except Exception as e:
        show_styled_critical(main_window, "Cannot open image", str(e))


def _nav_index_at_path(
    main_window, path: Optional[str]
) -> Optional[tuple[list[str], int]]:
    if main_window is None or not path:
        return None
    displayed = main_window.get_displayed_images()
    if not displayed or path not in displayed:
        return None
    return displayed, displayed.index(path)


def _current_nav_index(
    main_window, *, fallback_path: Optional[str] = None
) -> Optional[tuple[list[str], int]]:
    if main_window is None:
        return None
    displayed = main_window.get_displayed_images()
    if not displayed:
        return None
    current = main_window.get_current_image_path()
    if not current or current not in displayed:
        if fallback_path and fallback_path in displayed:
            current = fallback_path
        else:
            return None
    try:
        idx = displayed.index(current)
    except ValueError:
        idx = 0
    return displayed, idx


def _adjacent_displayed_path(
    displayed: list[str], idx: int, delta: int, *, wrap: bool
) -> Optional[str]:
    if len(displayed) <= 1:
        return None
    if delta < 0:
        if idx > 0:
            next_idx = idx - 1
        elif wrap:
            next_idx = len(displayed) - 1
        else:
            return None
    else:
        if idx < len(displayed) - 1:
            next_idx = idx + 1
        elif wrap:
            next_idx = 0
        else:
            return None
    return displayed[next_idx]


def can_navigate_source_prev_at(main_window, active_path: str) -> bool:
    """True when a previous image exists in the displayed list for active_path."""
    res = _nav_index_at_path(main_window, active_path)
    if not res:
        return False
    displayed, idx = res
    wrap = bool(getattr(main_window, "wrap_around", True))
    return _adjacent_displayed_path(displayed, idx, -1, wrap=wrap) is not None


def can_navigate_source_next_at(main_window, active_path: str) -> bool:
    """True when a next image exists in the displayed list for active_path."""
    res = _nav_index_at_path(main_window, active_path)
    if not res:
        return False
    displayed, idx = res
    wrap = bool(getattr(main_window, "wrap_around", True))
    return _adjacent_displayed_path(displayed, idx, 1, wrap=wrap) is not None


def navigate_source_image_at(
    main_window, delta: int, active_path: str
) -> Optional[str]:
    """Return adjacent displayed path without changing the main window."""
    res = _nav_index_at_path(main_window, active_path)
    if not res:
        return None
    displayed, idx = res
    wrap = bool(getattr(main_window, "wrap_around", True))
    return _adjacent_displayed_path(displayed, idx, delta, wrap=wrap)


def can_navigate_source_prev(
    main_window, *, fallback_path: Optional[str] = None
) -> bool:
    """True when show_previous_image would change the active image."""
    res = _current_nav_index(main_window, fallback_path=fallback_path)
    if not res:
        return False
    displayed, idx = res
    if len(displayed) <= 1:
        return False
    wrap = bool(getattr(main_window, "wrap_around", True))
    return idx > 0 or wrap


def can_navigate_source_next(
    main_window, *, fallback_path: Optional[str] = None
) -> bool:
    """True when show_next_image would change the active image."""
    res = _current_nav_index(main_window, fallback_path=fallback_path)
    if not res:
        return False
    displayed, idx = res
    if len(displayed) <= 1:
        return False
    wrap = bool(getattr(main_window, "wrap_around", True))
    return idx < len(displayed) - 1 or wrap


def navigate_source_image(
    main_window, delta: int, *, fallback_path: Optional[str] = None
) -> Optional[str]:
    """Move active image like keyboard arrows; returns new path or None."""
    if main_window is None:
        return None
    if delta < 0:
        if not can_navigate_source_prev(main_window, fallback_path=fallback_path):
            return None
    elif not can_navigate_source_next(main_window, fallback_path=fallback_path):
        return None

    if (
        fallback_path
        and fallback_path in (main_window.get_displayed_images() or [])
        and main_window.get_current_image_path() != fallback_path
    ):
        main_window.set_current_image_by_path(fallback_path)
        if main_window.current_view_mode == "thumbnail":
            main_window.highlight_image()

    if main_window.current_view_mode == "thumbnail":
        if getattr(main_window, "selected_files", None):
            main_window.clear_selection()
        main_window.range_anchor_index = None
        res = _current_nav_index(main_window, fallback_path=fallback_path)
        if not res:
            return None
        displayed, idx = res
        wrap = bool(getattr(main_window, "wrap_around", True))
        if delta < 0:
            if idx > 0:
                next_idx = idx - 1
            elif wrap:
                next_idx = len(displayed) - 1
            else:
                next_idx = idx
        else:
            if idx < len(displayed) - 1:
                next_idx = idx + 1
            elif wrap:
                next_idx = 0
            else:
                next_idx = idx
        next_path = displayed[next_idx]
        main_window.set_current_image_by_path(next_path)
        main_window.highlight_image()
        return next_path

    if delta < 0:
        main_window.show_previous_image()
    else:
        main_window.show_next_image()
    return main_window.get_current_image_path()


def _arrow_button_stylesheet() -> str:
    t = get_active_theme()
    return f"""
    QPushButton#imageGenNavPrev,
    QPushButton#imageGenNavNext {{
        background: transparent;
        border: none;
        color: {t.dialog_text_color_hex};
        font-size: 40px;
        font-weight: bold;
        padding: 4px 10px;
        min-width: 28px;
    }}
    QPushButton#imageGenNavPrev:hover,
    QPushButton#imageGenNavNext:hover {{
        color: {t.current_image_border_color_hex};
    }}
    """


class ImageGenSourceNavRow(QWidget):
    """Horizontal row: optional < and > flanking a center preview/canvas widget."""

    def __init__(
        self,
        main_window,
        on_source_changed: Callable[[str], None],
        parent=None,
        *,
        initial_source_path: Optional[str] = None,
    ):
        super().__init__(parent)
        self._main_window = main_window
        self._on_source_changed = on_source_changed
        self._active_source_path = initial_source_path

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        self._prev_btn = QPushButton("<")
        self._prev_btn.setObjectName("imageGenNavPrev")
        self._prev_btn.setFlat(True)
        self._prev_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._prev_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._prev_btn.clicked.connect(self._on_prev_clicked)

        self._next_btn = QPushButton(">")
        self._next_btn.setObjectName("imageGenNavNext")
        self._next_btn.setFlat(True)
        self._next_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._next_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._next_btn.clicked.connect(self._on_next_clicked)

        self._center_host = QWidget()
        self._center_layout = QHBoxLayout(self._center_host)
        self._center_layout.setContentsMargins(0, 0, 0, 0)
        self._center_layout.setSpacing(0)
        self._center_widget: Optional[QWidget] = None

        layout.addWidget(self._prev_btn, 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(self._center_host, 1)
        layout.addWidget(self._next_btn, 0, Qt.AlignmentFlag.AlignVCenter)

        from imagegen_plugins.image_gen_dialog import apply_image_gen_preview_client_background

        self.setStyleSheet(_arrow_button_stylesheet())
        apply_image_gen_preview_client_background(self)
        apply_image_gen_preview_client_background(self._center_host)
        self.refresh_arrows()

    def set_active_source_path(self, path: Optional[str]) -> None:
        self._active_source_path = path
        self.refresh_arrows()

    def set_center_widget(self, widget: QWidget) -> None:
        if self._center_widget is not None:
            self._center_layout.removeWidget(self._center_widget)
            self._center_widget.setParent(None)
        self._center_widget = widget
        widget.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self._center_layout.addWidget(widget, 1)

    def refresh_arrows(self) -> None:
        if not _qobject_alive(self) or not _qobject_alive(self._prev_btn):
            return
        mw = self._main_window
        if mw is None or mw.current_view_mode not in ("browse", "thumbnail"):
            self._prev_btn.setVisible(False)
            self._next_btn.setVisible(False)
            return
        fb = self._active_source_path
        if not fb:
            self._prev_btn.setVisible(False)
            self._next_btn.setVisible(False)
            return
        self._prev_btn.setVisible(can_navigate_source_prev_at(mw, fb))
        self._next_btn.setVisible(can_navigate_source_next_at(mw, fb))

    def _navigate(self, delta: int) -> None:
        active = self._active_source_path
        path = (
            navigate_source_image_at(self._main_window, delta, active)
            if active
            else None
        )
        if path:
            self._active_source_path = path
            self._on_source_changed(path)
        self.refresh_arrows()

    def navigate_prev(self) -> None:
        """Same as clicking the < source-image control."""
        self._navigate(-1)

    def navigate_next(self) -> None:
        """Same as clicking the > source-image control."""
        self._navigate(1)

    def _on_prev_clicked(self) -> None:
        self.navigate_prev()

    def _on_next_clicked(self) -> None:
        self.navigate_next()


class _SourceNavKeyFilter(QObject):
    """Option+Left/Right (Alt+arrows in Qt on macOS) — same as < > nav buttons."""

    def __init__(
        self, source_nav: ImageGenSourceNavRow | None, parent: QObject | None = None
    ):
        super().__init__(parent)
        self._source_nav = source_nav

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if event.type() != QEvent.Type.KeyPress:
            return False
        if not _qobject_alive(self._source_nav):
            return False
        key = event.key()
        if key not in (Qt.Key.Key_Left, Qt.Key.Key_Right):
            return False
        if not (event.modifiers() & Qt.KeyboardModifier.AltModifier):
            return False
        if key == Qt.Key.Key_Left:
            self._source_nav.navigate_prev()
        else:
            self._source_nav.navigate_next()
        return True


def _attach_source_nav_key_filter(host: QWidget) -> None:
    filt = getattr(host, "_image_gen_source_nav_key_filter", None)
    if filt is None:
        return
    tracked: set[int] = getattr(host, "_image_gen_source_nav_key_filter_widgets", None) or set()
    for widget in (host, *host.findChildren(QWidget)):
        wid = id(widget)
        if wid in tracked:
            continue
        widget.installEventFilter(filt)
        tracked.add(wid)
    setattr(host, "_image_gen_source_nav_key_filter_widgets", tracked)


def install_source_nav_keyboard_shortcuts(
    host: QWidget, source_nav: ImageGenSourceNavRow | None
) -> None:
    """Option+Left / Option+Right — prev/next source image (all dialog focus targets)."""
    filt = getattr(host, "_image_gen_source_nav_key_filter", None)
    if filt is None:
        filt = _SourceNavKeyFilter(source_nav, parent=host)
        setattr(host, "_image_gen_source_nav_key_filter", filt)
    else:
        filt._source_nav = source_nav
    _attach_source_nav_key_filter(host)


def refresh_source_nav_keyboard_shortcuts(host: QWidget) -> None:
    """Attach key filter to widgets added after install (e.g. dynamic field rows)."""
    _attach_source_nav_key_filter(host)
