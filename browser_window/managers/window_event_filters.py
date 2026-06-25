#!/usr/bin/env python3
"""QObject event filters installed on the main window."""

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtGui import QCursor, QKeyEvent
from PySide6.QtWidgets import QApplication

CURSOR_PEEK_ZONE_HEIGHT = 35  # Height of the cursor peek zone in pixels


class StatusBarPeekFilter(QObject):
    """App-level event filter to catch MouseMove from any child widget for status bar peek zone."""

    def __init__(self, main_window, parent=None):
        super().__init__(parent)
        self.main_window = main_window

    def eventFilter(self, obj, event):
        if getattr(self.main_window, '_chrome_suppressed', False):
            return False
        if event.type() == QEvent.MouseMove and hasattr(obj, 'window') and obj.window() == self.main_window:
            if hasattr(self.main_window, 'status_bar'):
                cursor_y = self.main_window.mapFromGlobal(QCursor.pos()).y()
                in_zone = cursor_y >= self.main_window.height() - CURSOR_PEEK_ZONE_HEIGHT
                if not self.main_window.status_bar.isVisible() and in_zone:
                    self.main_window._status_bar_peek_active = True
                    self.main_window._animate_status_bar_show(self.main_window._peek_layout_update)
                elif self.main_window._status_bar_peek_active and not in_zone:
                    self.main_window._status_bar_peek_active = False
                    self.main_window._animate_status_bar_hide(self.main_window._peek_layout_update)
        return False


class ChromeToggleShortcutFilter(QObject):
    """App-level event filter for F4, . toggle-chrome (main window only, not dialogs)."""

    def __init__(self, main_window, parent=None):
        super().__init__(parent)
        self.main_window = main_window

    def eventFilter(self, obj, event):
        if event.type() == QEvent.KeyPress and isinstance(event, QKeyEvent):
            if event.key() == Qt.Key_F4 and not event.modifiers():
                mw = self.main_window
                if not mw.isVisible():
                    return False
                if hasattr(mw, '_is_main_window_key_context') and not mw._is_main_window_key_context():
                    return False
                if hasattr(mw, 'toggle_chrome'):
                    mw.toggle_chrome()
                    return True
        return False


class ShiftCmdEShortcutFilter(QObject):
    """App-level event filter for shift-cmd-E and shift-cmd-U before Qt shortcut processing."""

    def __init__(self, main_window, parent=None):
        super().__init__(parent)
        self.main_window = main_window

    def eventFilter(self, obj, event):
        if event.type() == QEvent.KeyPress and isinstance(event, QKeyEvent):
            mods = event.modifiers()
            ctrl_or_cmd = (mods & Qt.ShiftModifier) and (mods & (Qt.ControlModifier | Qt.MetaModifier)) and not (mods & Qt.AltModifier)
            active = QApplication.activeWindow()
            if active == self.main_window and self.main_window.isVisible() and ctrl_or_cmd:
                if event.key() == Qt.Key_E:
                    if hasattr(self.main_window, 'edit_exif_usercomment'):
                        self.main_window.edit_exif_usercomment()
                        return True
                elif event.key() == Qt.Key_U:
                    if hasattr(self.main_window, 'create_screen_size_copy'):
                        self.main_window.create_screen_size_copy()
                        return True
        return False
