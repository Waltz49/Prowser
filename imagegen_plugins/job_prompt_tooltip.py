#!/usr/bin/env python3
"""Delayed hover tooltip for full prompt text on job queue / status panels."""

from __future__ import annotations

import time

from PySide6.QtCore import QEvent, QObject, QPoint, QTimer, Qt
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import QApplication, QLabel, QWidget

from imagegen_plugins.model_task_status_info import full_prompt_tooltip_text
from tooltip_popup_utils import (
    TOOLTIP_MARGIN,
    clamp_bounds_for_widget,
    position_tooltip_near_cursor,
)

_POLL_MS = 100
_DEFAULT_MAX_WIDTH = 520


class _PromptTooltipPopup(QLabel):
    """Floating label — avoids macOS QToolTip auto-dismiss after show."""

    def __init__(self, text: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.setText(text)
        self.setWordWrap(True)
        self.setMaximumWidth(_DEFAULT_MAX_WIDTH)
        self.setWindowFlags(
            Qt.WindowType.ToolTip | Qt.WindowType.FramelessWindowHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        from theme.theme_service import get_active_theme

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
        bounds = clamp_bounds_for_widget(clamp_widget)
        margin = TOOLTIP_MARGIN
        max_w = max(160, bounds.width() - 2 * margin)
        self.setMaximumWidth(min(_DEFAULT_MAX_WIDTH, max_w))
        self.adjustSize()
        position_tooltip_near_cursor(self, clamp_widget=clamp_widget, margin=margin)
        self.show()
        self.raise_()

    def contains_global(self, global_pos: QPoint) -> bool:
        return self.isVisible() and self.geometry().contains(global_pos)


class _GlobalPromptTooltipDismissFilter(QObject):
    """Dismiss the active prompt tooltip on any mouse press outside the host filter."""

    def __init__(self) -> None:
        super().__init__(QApplication.instance())
        self._active: _DelayedPromptTooltipFilter | None = None

    def set_active(self, filt: _DelayedPromptTooltipFilter | None) -> None:
        self._active = filt

    def clear_active_if(self, filt: _DelayedPromptTooltipFilter) -> None:
        if self._active is filt:
            self._active = None

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        if (
            self._active is not None
            and self._active._is_visible()
            and event.type() == QEvent.Type.MouseButtonPress
        ):
            self._active._dismiss()
        return False


_global_dismiss_filter: _GlobalPromptTooltipDismissFilter | None = None


def _global_dismiss_filter_instance() -> _GlobalPromptTooltipDismissFilter:
    global _global_dismiss_filter
    if _global_dismiss_filter is None:
        app = QApplication.instance()
        _global_dismiss_filter = _GlobalPromptTooltipDismissFilter()
        app.installEventFilter(_global_dismiss_filter)
    return _global_dismiss_filter


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
        host_widget.destroyed.connect(self._on_host_destroyed)

    def _on_host_destroyed(self, _obj: QObject | None = None) -> None:
        self._dismiss()

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

    def _host_effective_visible(self) -> bool:
        host = self._host_widget
        if host is None:
            return False
        try:
            if not host.isVisible():
                return False
            win = host.window()
            if win is None or not win.isVisible():
                return False
        except RuntimeError:
            return False
        return True

    def _host_under_cursor(self, global_pos: QPoint) -> bool:
        host = self._host_widget
        if not self._host_effective_visible():
            return False
        return host.rect().contains(host.mapFromGlobal(global_pos))

    def _on_show_timeout(self) -> None:
        pos = QCursor.pos()
        if not self._host_under_cursor(pos):
            return
        if self._popup is None:
            self._popup = _PromptTooltipPopup(self._text, parent=self._host_widget)
        self._popup.show_near_cursor(self._host_widget)
        _global_dismiss_filter_instance().set_active(self)
        self._poll_timer.start()

    def _poll_hover(self) -> None:
        if not self._is_visible():
            self._poll_timer.stop()
            return
        if not self._host_effective_visible():
            self._dismiss()
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
        if _global_dismiss_filter is not None:
            _global_dismiss_filter.clear_active_if(self)
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
