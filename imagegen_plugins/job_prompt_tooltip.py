#!/usr/bin/env python3
"""Delayed hover tooltip for full prompt text on job queue / status panels."""

from __future__ import annotations

import time

from PySide6.QtCore import QEvent, QObject, QPoint, QRect, QTimer, Qt
from PySide6.QtGui import QCursor, QGuiApplication
from PySide6.QtWidgets import QLabel, QMenu, QWidget

from imagegen_plugins.model_task_status_info import full_prompt_tooltip_text

_POLL_MS = 100
_MARGIN = 10
_DEFAULT_MAX_WIDTH = 520


def _clamp_bounds_for_widget(widget: QWidget | None) -> QRect:
    """Global rect to keep the popup inside (host window, else screen)."""
    if widget is not None:
        win = widget.window()
        if win is not None and win.isVisible() and not isinstance(win, QMenu):
            return win.frameGeometry()
    screen = QGuiApplication.screenAt(QCursor.pos())
    if screen is not None:
        return screen.availableGeometry()
    return QRect(0, 0, 1920, 1080)


def _clamp_popup_position(
    global_pos: QPoint, size, bounds: QRect, *, margin: int = _MARGIN
) -> QPoint:
    x, y = global_pos.x(), global_pos.y()
    left = bounds.left() + margin
    top = bounds.top() + margin
    right = bounds.right() - margin - size.width()
    bottom = bounds.bottom() - margin - size.height()
    return QPoint(max(left, min(x, right)), max(top, min(y, bottom)))


class _PromptTooltipPopup(QLabel):
    """Floating label — avoids macOS QToolTip auto-dismiss after show."""

    def __init__(self, text: str):
        super().__init__(None)
        self.setText(text)
        self.setWordWrap(True)
        self.setMaximumWidth(_DEFAULT_MAX_WIDTH)
        self.setWindowFlags(
            Qt.WindowType.ToolTip | Qt.WindowType.FramelessWindowHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        from theme_service import get_active_theme

        t = get_active_theme()
        self.setStyleSheet(
            f"""
            QLabel {{
                background-color: {t.dialog_background_hex};
                color: {t.dialog_text_color_hex};
                border: 1px solid {t.border_default_hex};
                border-radius: 4px;
                padding: 8px 10px;
                font-size: 12px;
            }}
            """
        )

    def show_near_cursor(self, clamp_widget: QWidget | None = None) -> None:
        bounds = _clamp_bounds_for_widget(clamp_widget)
        margin = _MARGIN
        max_w = max(160, bounds.width() - 2 * margin)
        self.setMaximumWidth(min(_DEFAULT_MAX_WIDTH, max_w))

        cursor = QCursor.pos()
        # Prefer below-right of cursor; flip when that would clip.
        x = cursor.x() + 12
        y = cursor.y() + 20
        self.adjustSize()
        size = self.size()
        if x + size.width() > bounds.right() - margin:
            x = cursor.x() - size.width() - 12
        if y + size.height() > bounds.bottom() - margin:
            y = cursor.y() - size.height() - 12

        pos = _clamp_popup_position(QPoint(x, y), size, bounds, margin=margin)
        self.move(pos)
        self.show()
        self.raise_()

    def contains_global(self, global_pos: QPoint) -> bool:
        return self.isVisible() and self.geometry().contains(global_pos)


class _DelayedPromptTooltipFilter(QObject):
    """1s delayed show; dismiss only when cursor leaves host and popup (polled)."""

    def __init__(
        self,
        text: str,
        host_widget: QWidget,
        *,
        delay_ms: int = 1000,
        parent=None,
    ):
        super().__init__(parent)
        self._text = text
        self._host_widget = host_widget
        self._delay_ms = delay_ms
        self._popup: _PromptTooltipPopup | None = None
        self._suppress_dismiss_until = 0.0
        self._show_timer = QTimer(self)
        self._show_timer.setSingleShot(True)
        self._show_timer.timeout.connect(self._on_show_timeout)
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(_POLL_MS)
        self._poll_timer.timeout.connect(self._poll_hover)

    def brief_suppress_dismiss(self, ms: int = 200) -> None:
        """Ignore hover-out briefly during HTML/height refresh of the host."""
        self._suppress_dismiss_until = time.monotonic() + ms / 1000.0

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        if not self._text:
            return False
        et = event.type()
        if et == QEvent.Type.Enter:
            if not self._is_visible():
                self._show_timer.start(self._delay_ms)
        elif et == QEvent.Type.Leave:
            self._show_timer.stop()
        elif et == QEvent.Type.MouseButtonPress:
            self._dismiss()
        return False

    def _is_visible(self) -> bool:
        return self._popup is not None and self._popup.isVisible()

    def _host_under_cursor(self, global_pos: QPoint) -> bool:
        host = self._host_widget
        if host is None or not host.isVisible():
            return False
        return host.rect().contains(host.mapFromGlobal(global_pos))

    def _on_show_timeout(self) -> None:
        pos = QCursor.pos()
        if not self._host_under_cursor(pos):
            return
        if self._popup is None:
            self._popup = _PromptTooltipPopup(self._text)
        self._popup.show_near_cursor(self._host_widget)
        self._poll_timer.start()

    def _poll_hover(self) -> None:
        if not self._is_visible():
            self._poll_timer.stop()
            return
        if time.monotonic() < self._suppress_dismiss_until:
            return
        pos = QCursor.pos()
        if self._host_under_cursor(pos):
            return
        if self._popup is not None and self._popup.contains_global(pos):
            return
        self._dismiss()

    def _dismiss(self) -> None:
        self._show_timer.stop()
        self._poll_timer.stop()
        if self._popup is not None:
            self._popup.hide()
        self._suppress_dismiss_until = 0.0


def notify_job_prompt_tooltip_content_updating(widget: QWidget) -> None:
    """Call before refreshing host HTML so a live update does not dismiss the popup."""
    filt = getattr(widget, "_job_prompt_tooltip_filter", None)
    if filt is not None:
        filt.brief_suppress_dismiss()


def install_delayed_prompt_tooltip(
    widget: QWidget,
    full_prompt: str,
    *,
    delay_ms: int = 1000,
) -> None:
    """Attach a 1s-delay tooltip when ``full_prompt`` is truncated for display."""
    tip = full_prompt_tooltip_text(full_prompt)
    if not tip:
        return
    filt = _DelayedPromptTooltipFilter(
        tip, widget, delay_ms=delay_ms, parent=widget
    )
    widget.installEventFilter(filt)
    viewport = widget.viewport() if hasattr(widget, "viewport") else None
    if viewport is not None:
        viewport.installEventFilter(filt)
    widget._job_prompt_tooltip_filter = filt  # type: ignore[attr-defined]
