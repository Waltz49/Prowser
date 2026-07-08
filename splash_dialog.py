#!/usr/bin/env python3
"""Startup splash screen for Prowser."""

from __future__ import annotations

import time
from typing import Optional, TYPE_CHECKING

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QBitmap, QPainter, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from theme.theme_base import asset_path
from utils import _center_styled_dialog_on_screen, _make_native_window_key, activate_macos_application

if TYPE_CHECKING:
    from config import ImageBrowserConfig

SPLASH_POST_SETTLE_DELAY_MS = 2350
MIN_WINDOW_SETTLE_MS = 500
KEEP_ON_TOP_INTERVAL_MS = 80
_SETTLE_FALLBACK_MS = 8000

_active_splash: Optional["SplashScreen"] = None
_pending_main_window: Optional[QWidget] = None
_keep_on_top_timer: Optional[QTimer] = None
_dismiss_timer: Optional[QTimer] = None
_settle_fallback_timer: Optional[QTimer] = None
_window_shown_at_monotonic: Optional[float] = None
_delayed_refresh_done = False
_has_configuration_refresh = False
_settle_countdown_started = False


SPLASH_CORNER_RADIUS = 34


def _apply_rounded_mask(widget: QWidget, radius: int) -> None:
    """Clip the splash window to rounded corners."""
    w, h = widget.width(), widget.height()
    if w <= 0 or h <= 0:
        return
    bitmap = QBitmap(w, h)
    bitmap.fill(Qt.GlobalColor.color0)
    painter = QPainter(bitmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setBrush(Qt.GlobalColor.color1)
    painter.setPen(Qt.NoPen)
    painter.drawRoundedRect(0, 0, w, h, radius, radius)
    painter.end()
    widget.setMask(bitmap)


class SplashScreen(QWidget):
    """640x480 splash with a lower-right 'Do not show again' checkbox."""

    _SIZE = (640, 480)

    def __init__(self, config: "ImageBrowserConfig", parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._config = config
        self._centered = False
        self.setWindowTitle("Prowser")
        self.setFixedSize(*self._SIZE)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setStyleSheet("background: transparent;")
        self.setWindowFlags(
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.WindowDoesNotAcceptFocus
        )

        pixmap = QPixmap(asset_path("splash.webp"))
        if pixmap.isNull():
            pixmap = QPixmap(*self._SIZE)
            pixmap.fill(Qt.GlobalColor.darkBlue)

        container = QWidget(self)
        container.setFixedSize(*self._SIZE)
        container.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        container.setStyleSheet("background: transparent;")

        image_label = QLabel(container)
        image_label.setPixmap(pixmap)
        image_label.setGeometry(0, 0, *self._SIZE)
        image_label.setStyleSheet("background: transparent;")

        self._skip_checkbox = QCheckBox("Do not show again", container)
        self._skip_checkbox.setStyleSheet(
            "QCheckBox {"
            "  color: #ffffff;"
            "  font-size: 13px;"
            "  background: transparent;"
            "  padding: 6px 10px;"
            "}"
            "QCheckBox::indicator {"
            "  width: 14px;"
            "  height: 14px;"
            "  border: 1.5px solid #ffffff;"
            "  border-radius: 3px;"
            "  background-color: rgba(255, 255, 255, 0.15);"
            "}"
            "QCheckBox::indicator:checked {"
            f"  image: url({asset_path('checkbox_x.svg').replace(chr(92), '/')});"
            "  background-color: #ffffff;"
            "}"
        )

        footer = QHBoxLayout()
        footer.setContentsMargins(0, 0, 16, 14)
        footer.addStretch(1)
        footer.addWidget(self._skip_checkbox, 0, Qt.AlignmentFlag.AlignRight)

        footer_host = QWidget(container)
        footer_host.setGeometry(0, self._SIZE[1] - 44, self._SIZE[0], 44)
        footer_host.setLayout(footer)
        footer_host.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)

        self._skip_checkbox.stateChanged.connect(self._on_skip_state_changed)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(container)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        _apply_rounded_mask(self, SPLASH_CORNER_RADIUS)
        if self._centered:
            return
        self._centered = True
        QTimer.singleShot(0, lambda: _center_styled_dialog_on_screen(self, self.parentWidget()))

    def do_not_show_again(self) -> bool:
        return self._skip_checkbox.isChecked()

    def _on_skip_state_changed(self, _state: int) -> None:
        try:
            self._config.update_setting("show_splash", not self._skip_checkbox.isChecked())
        except Exception:
            pass


def _stop_keep_on_top() -> None:
    global _keep_on_top_timer
    if _keep_on_top_timer is not None:
        _keep_on_top_timer.stop()
        _keep_on_top_timer.deleteLater()
        _keep_on_top_timer = None


def _start_keep_on_top() -> None:
    global _keep_on_top_timer
    _stop_keep_on_top()
    _keep_on_top_timer = QTimer()
    _keep_on_top_timer.setInterval(KEEP_ON_TOP_INTERVAL_MS)

    def _raise_splash() -> None:
        splash = _active_splash
        if splash is None:
            _stop_keep_on_top()
            return
        if splash.isVisible():
            splash.show()
            splash.raise_()

    _keep_on_top_timer.timeout.connect(_raise_splash)
    _keep_on_top_timer.start()


def _stop_settle_fallback() -> None:
    global _settle_fallback_timer
    if _settle_fallback_timer is not None:
        _settle_fallback_timer.stop()
        _settle_fallback_timer.deleteLater()
        _settle_fallback_timer = None


def _begin_post_settle_dismiss_countdown() -> None:
    global _settle_countdown_started, _dismiss_timer
    if _settle_countdown_started or _active_splash is None:
        return
    _settle_countdown_started = True
    _stop_settle_fallback()
    if _dismiss_timer is not None:
        _dismiss_timer.stop()
        _dismiss_timer.deleteLater()
    _dismiss_timer = QTimer()
    _dismiss_timer.setSingleShot(True)
    _dismiss_timer.timeout.connect(dismiss_splash)
    _dismiss_timer.start(SPLASH_POST_SETTLE_DELAY_MS)


def _try_start_post_settle_dismiss() -> None:
    if _settle_countdown_started or _active_splash is None:
        return
    if _window_shown_at_monotonic is None:
        return
    if _has_configuration_refresh and not _delayed_refresh_done:
        return

    elapsed_ms = (time.monotonic() - _window_shown_at_monotonic) * 1000
    remaining_settle_ms = max(0, int(MIN_WINDOW_SETTLE_MS - elapsed_ms))
    QTimer.singleShot(remaining_settle_ms, _begin_post_settle_dismiss_countdown)


def should_show_startup_splash(config: "ImageBrowserConfig", args) -> bool:
    """Return True unless the user opted out or passed --no-splash."""
    if getattr(args, "splash", False):
        return True
    return bool(config.load_settings().get("show_splash", True))


def show_splash_async(config: "ImageBrowserConfig", parent: Optional[QWidget] = None) -> SplashScreen:
    """Show the splash screen without blocking startup."""
    global _active_splash
    if _active_splash is not None:
        return _active_splash

    splash = SplashScreen(config, parent)
    _active_splash = splash
    activate_macos_application(force=True)
    splash.show()
    splash.raise_()
    splash.repaint()
    _make_native_window_key(splash)
    _start_keep_on_top()
    app = QApplication.instance()
    if app is not None:
        app.processEvents()
    return splash


def on_main_window_shown(window: QWidget) -> None:
    """Record main-window show time and keep splash above setup work."""
    global _pending_main_window, _window_shown_at_monotonic, _settle_fallback_timer
    _pending_main_window = window
    _window_shown_at_monotonic = time.monotonic()
    _start_keep_on_top()
    _stop_settle_fallback()
    _settle_fallback_timer = QTimer()
    _settle_fallback_timer.setSingleShot(True)
    _settle_fallback_timer.timeout.connect(_begin_post_settle_dismiss_countdown)
    _settle_fallback_timer.start(_SETTLE_FALLBACK_MS)


def on_startup_refresh_scheduled() -> None:
    """Startup will run delayed_refresh before the window is considered settled."""
    global _has_configuration_refresh
    _has_configuration_refresh = True


def on_startup_refresh_complete(window: QWidget) -> None:
    """Initial configuration refresh finished; start post-settle dismiss countdown."""
    global _delayed_refresh_done, _pending_main_window
    _pending_main_window = window
    _delayed_refresh_done = True
    _try_start_post_settle_dismiss()


def dismiss_splash() -> None:
    """Hide the splash and persist the do-not-show preference if checked."""
    global _active_splash, _pending_main_window
    global _dismiss_timer, _settle_countdown_started
    global _delayed_refresh_done, _has_configuration_refresh
    global _window_shown_at_monotonic

    splash = _active_splash
    if splash is None:
        return

    _active_splash = None
    _settle_countdown_started = False
    _delayed_refresh_done = False
    _has_configuration_refresh = False
    _window_shown_at_monotonic = None
    _stop_keep_on_top()
    _stop_settle_fallback()
    if _dismiss_timer is not None:
        _dismiss_timer.stop()
        _dismiss_timer.deleteLater()
        _dismiss_timer = None

    if splash.do_not_show_again():
        splash._config.update_setting("show_splash", False)

    main_window = _pending_main_window
    splash.close()
    splash.deleteLater()

    if main_window is not None:
        from utils import activate_application_window, schedule_startup_activation

        activate_application_window(main_window, force=True)
        schedule_startup_activation(main_window, force=True)
