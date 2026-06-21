#!/usr/bin/env python3
"""
Idle Detector for Image Browser
Tracks user activity (mouse/keyboard events) and detects when the system is idle.
"""

from PySide6.QtCore import QObject, QTimer, Signal, QEvent
from PySide6.QtWidgets import QApplication
from thumbnails.thumbnail_constants import BACKGROUND_CLIP_IDLE_TIMEOUT_SECONDS


class IdleDetector(QObject):
    """Detects when the user has been idle for a specified duration"""
    
    idle_detected = Signal()  # Emitted when idle threshold is reached
    user_activity_detected = Signal()  # Emitted when user activity is detected
    
    def __init__(self, main_window, parent=None):
        """
        Initialize idle detector
        
        Args:
            main_window: Reference to the main ImageBrowserWindow instance
            parent: Parent QObject
        """
        super().__init__(parent)
        self.main_window = main_window
        self.idle_timer = QTimer()
        self.idle_timer.setSingleShot(True)
        self.idle_timer.timeout.connect(self._on_idle_timeout)
        self.idle_timeout_ms = BACKGROUND_CLIP_IDLE_TIMEOUT_SECONDS * 1000
        
        # Install event filter on QApplication to catch user activity events
        # This ensures we catch keypresses and mouse clicks over child widgets too
        app = QApplication.instance()
        if app:
            app.installEventFilter(self)
    
    def start(self):
        """Start idle detection"""
        self.reset()
    
    def stop(self):
        """Stop idle detection"""
        self.idle_timer.stop()
    
    def reset(self):
        """Reset idle timer (call when user activity detected)"""
        was_running = self.idle_timer.isActive()
        self.idle_timer.stop()
        self.idle_timer.start(self.idle_timeout_ms)
        
        # Emit signal if timer was running (meaning background process was active)
        if was_running:
            self.user_activity_detected.emit()
    
    def _on_idle_timeout(self):
        """Called when idle timeout is reached"""
        self.idle_detected.emit()
    
    def eventFilter(self, obj, event):
        """Event filter to detect user activity"""
        # Process events from any widget in the application
        # This ensures we catch mouse clicks and keypresses over child widgets
        
        # Detect user activity events - only keypress and mouse clicks
        # Mouse movements are excluded to avoid pausing background process unnecessarily
        event_type = event.type()
        if event_type in (
            QEvent.KeyPress,
            QEvent.KeyRelease,
            QEvent.MouseButtonPress,
            QEvent.MouseButtonRelease,
            QEvent.MouseButtonDblClick
        ):
            # Reset idle timer on keypress or mouse click
            # This will also emit user_activity_detected signal if timer was running
            self.reset()
        
        return False  # Don't consume the event, let it propagate
