"""
Cursor Manager for Image Browser

A generalized cursor management system that hides the cursor after inactivity
and shows it on movement. Designed to be reusable across different view modes.
"""

from PySide6.QtCore import QTimer, QObject, QEvent
from PySide6.QtWidgets import QWidget, QApplication
from PySide6.QtGui import Qt, QCursor


class CursorManager(QObject):
    """
    Manages cursor visibility based on mouse movement.
    
    Hides the cursor after a specified period of inactivity and shows it
    again when the mouse moves. Designed to be attached to any QWidget.
    Now uses a global event filter to catch all mouse events (for macOS compatibility).
    """
    
    def __init__(self, widget: QWidget, hide_delay_ms: int = 2000, parent=None):
        """
        Initialize the cursor manager.
        
        Args:
            widget: The widget to monitor for mouse events
            hide_delay_ms: Milliseconds to wait before hiding cursor (default: 2000)
            parent: Parent QObject
        """
        super().__init__(parent)
        
        self.widget = widget
        self.hide_delay_ms = hide_delay_ms
        self.is_cursor_hidden = False
        self._over_hide_zone = False
        self._paused = False
        
        # Timer for hiding cursor after inactivity
        self.hide_timer = QTimer(self)
        self.hide_timer.setSingleShot(True)
        self.hide_timer.timeout.connect(self._hide_cursor)
        
        # Store original cursor for restoration
        self.original_cursor = widget.cursor()
        
        # Install global event filter
        app = QApplication.instance()
        if app:
            app.installEventFilter(self)
    
    def _is_over_hide_zone(self) -> bool:
        """True when the cursor is over the browse canvas (self.widget) or its children."""
        widget = self.widget
        if widget is None or not widget.isVisible():
            return False
        app = QApplication.instance()
        if app is None:
            return False
        w = app.widgetAt(QCursor.pos())
        while w is not None:
            if w is widget:
                return True
            w = w.parentWidget()
        return False

    def _update_hide_zone_state(self):
        """Track enter/leave of the hide zone; show cursor and stop timer on leave."""
        over = self._is_over_hide_zone()
        if over == self._over_hide_zone:
            return
        self._over_hide_zone = over
        if over:
            self.hide_timer.start(self.hide_delay_ms)
        else:
            self.hide_timer.stop()
            if self.is_cursor_hidden:
                self._show_cursor()

    def eventFilter(self, obj, event):
        """
        Event filter to catch mouse events and manage cursor visibility.
        
        Args:
            obj: The object that generated the event
            event: The event that occurred
            
        Returns:
            bool: True if event was handled, False to pass to parent
        """
        # Don't process events when paused
        if self._paused:
            return False
            
        # Listen for mouse movement and button events globally
        if event.type() in (QEvent.MouseMove, QEvent.MouseButtonPress, QEvent.MouseButtonRelease, QEvent.Wheel):
            self._update_hide_zone_state()
            if self._over_hide_zone:
                self._on_activity_in_zone()
        return super().eventFilter(obj, event)
    
    def _on_activity_in_zone(self):
        """Restart hide timer while the cursor is over the browse canvas."""
        if self.is_cursor_hidden:
            self._show_cursor()
        self.hide_timer.start(self.hide_delay_ms)

    def on_mouse_activity(self):
        """
        Manual method to trigger mouse activity (for use without event filter).
        Call this from mouse event handlers.
        """
        if self._paused:
            return
        self._update_hide_zone_state()
        if self._over_hide_zone:
            self._on_activity_in_zone()
    
    def _hide_cursor(self):
        """Hide the cursor only while it remains over the browse canvas."""
        if not self._is_over_hide_zone():
            return
        if not self.is_cursor_hidden:
            # Set cursor on both widget and application level for better visibility
            self.widget.setCursor(Qt.BlankCursor)
            app = QApplication.instance()
            if app:
                app.setOverrideCursor(Qt.BlankCursor)
            self.is_cursor_hidden = True
    
    def _show_cursor(self):
        """Show the cursor using the original cursor."""
        if self.is_cursor_hidden:
            # For macOS, try a more aggressive approach
            app = QApplication.instance()
            if app:
                # Clear any override cursors first
                app.restoreOverrideCursor()
                # Force a cursor change to trigger redraw
                app.setOverrideCursor(self.original_cursor)
                app.restoreOverrideCursor()
            
            # Set cursor on widget
            self.widget.setCursor(self.original_cursor)
            self.is_cursor_hidden = False
    
    def set_cursor(self, cursor):
        """
        Set a specific cursor and update the original cursor reference.
        This allows the cursor manager to work with dynamic cursor changes.
        
        Args:
            cursor: The cursor to set
        """
        self.widget.setCursor(cursor)
        # Update the original cursor reference so it can be restored later
        self.original_cursor = cursor
        # If cursor was hidden, show it now
        if self.is_cursor_hidden:
            self.is_cursor_hidden = False
    
    def start(self):
        """Start cursor management (starts the hide timer when over the browse canvas)."""
        self._over_hide_zone = self._is_over_hide_zone()
        if self._over_hide_zone:
            self.hide_timer.start(self.hide_delay_ms)
    
    def stop(self):
        """Stop cursor management and ensure cursor is visible."""
        self.hide_timer.stop()
        if self.is_cursor_hidden:
            self._show_cursor()
    
    def cleanup(self):
        """Clean up resources and restore original cursor."""
        self.stop()
        app = QApplication.instance()
        if app:
            app.removeEventFilter(self)
    
    def disable(self):
        """Completely disable cursor management and restore cursor."""
        self.stop()
        if self.is_cursor_hidden:
            self._show_cursor()
        app = QApplication.instance()
        if app:
            app.removeEventFilter(self)
        # Reset state
        self.is_cursor_hidden = False
        self._paused = True 