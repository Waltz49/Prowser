#!/usr/bin/env python3
"""Prev/next source image controls for edit and expand dialogs."""

from __future__ import annotations

from typing import Callable, Optional

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtWidgets import QHBoxLayout, QPushButton, QSizePolicy, QWidget

from theme_service import get_active_theme


def resolve_image_gen_main_window(dialog: QWidget):
    """Parent main window when the dialog was opened with main_window as parent."""
    parent = dialog.parent() if dialog is not None else None
    if parent is not None and hasattr(parent, "current_view_mode"):
        return parent
    return None


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

        self.setStyleSheet(_arrow_button_stylesheet())
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
        mw = self._main_window
        if mw is None or mw.current_view_mode not in ("browse", "thumbnail"):
            self._prev_btn.setVisible(False)
            self._next_btn.setVisible(False)
            return
        fb = self._active_source_path
        self._prev_btn.setVisible(can_navigate_source_prev(mw, fallback_path=fb))
        self._next_btn.setVisible(can_navigate_source_next(mw, fallback_path=fb))

    def _navigate(self, delta: int) -> None:
        path = navigate_source_image(
            self._main_window, delta, fallback_path=self._active_source_path
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

    def __init__(self, source_nav: ImageGenSourceNavRow, parent: QObject | None = None):
        super().__init__(parent)
        self._source_nav = source_nav

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if event.type() != QEvent.Type.KeyPress:
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
    host: QWidget, source_nav: ImageGenSourceNavRow
) -> None:
    """Option+Left / Option+Right — prev/next source image (all dialog focus targets)."""
    filt = getattr(host, "_image_gen_source_nav_key_filter", None)
    if filt is None:
        filt = _SourceNavKeyFilter(source_nav, parent=host)
        setattr(host, "_image_gen_source_nav_key_filter", filt)
    _attach_source_nav_key_filter(host)


def refresh_source_nav_keyboard_shortcuts(host: QWidget) -> None:
    """Attach key filter to widgets added after install (e.g. dynamic field rows)."""
    _attach_source_nav_key_filter(host)
