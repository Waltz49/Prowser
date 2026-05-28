#!/usr/bin/env python3
"""
Event Handler
Handles Qt events (keyboard, mouse, resize, etc.)
"""

from PySide6.QtCore import QEvent, Qt, QTimer
from PySide6.QtGui import QKeyEvent, QResizeEvent
from PySide6.QtWidgets import QApplication


class EventHandler:
    """Manages event handling for the main window"""
    
    def __init__(self, main_window):
        """
        Initialize the event handler
        
        Args:
            main_window: Reference to the main ImageBrowserWindow instance
        """
        self.main_window = main_window
    
    def keyPressEvent(self, event: QKeyEvent):
        """Handle keyboard events using the centralized keyboard handler system"""
        from qt_key_debug import log_key_event
        log_key_event(event)
        
        # Debug cmd-shift-return
        if event.key() in [Qt.Key_Return, Qt.Key_Enter]:
            modifiers = event.modifiers()
            cmd_shift = (modifiers & Qt.ShiftModifier) and (modifiers & (Qt.ControlModifier | Qt.MetaModifier))
        
        # Check if help dialog is visible - if so, let it handle keyboard events
        if (hasattr(self.main_window, 'help_dialog') and self.main_window.help_dialog and 
            self.main_window.help_dialog.isVisible() and self.main_window.help_dialog.dialog):
            # Forward the event to the dialog
            focused_widget = QApplication.focusWidget()
            if focused_widget == self.main_window.help_dialog.dialog or focused_widget is None:
                # Let the dialog handle the event
                if hasattr(self.main_window.help_dialog.dialog, 'keyPressEvent'):
                    self.main_window.help_dialog.dialog.keyPressEvent(event)
                    return True
            # If dialog has focus, don't process here
            if focused_widget and self.main_window.help_dialog.dialog.isAncestorOf(focused_widget):
                super().keyPressEvent(event)
                return True
        
        # Check which widget has focus and route events appropriately
        focused_widget = QApplication.focusWidget()
        
        # Tab key - let Qt handle navigation
        if event.key() == Qt.Key_Tab:
            super().keyPressEvent(event)
            return True
        
        # Handle Cmd+Z (Undo) directly to ensure it works before menu is shown
        # This matches how Cmd+C works - Qt processes it even if menu hasn't been shown
        # Trigger undo directly regardless of action enabled state (action disabled state is just for menu display)
        if (event.key() == Qt.Key_Z and 
            (event.modifiers() & Qt.ControlModifier) and
            not (event.modifiers() & Qt.ShiftModifier) and
            not (event.modifiers() & Qt.AltModifier)):
            # Call undo_file_operation directly instead of triggering the action
            # This works even when the action is disabled (disabled state is just for menu display)
            if hasattr(self.main_window, 'file_operations_manager') and self.main_window.file_operations_manager:
                self.main_window.undo_file_operation()
                event.accept()
                return True
        
        # Route keyboard events based on which widget has focus
        if focused_widget == self.main_window.tree_container:
            # Route keyboard events to the tree view
            if (hasattr(self.main_window, 'file_tree_handler') and 
                self.main_window.file_tree_handler.is_tree_initialized() and 
                hasattr(self.main_window.file_tree_handler, 'file_tree')):
                self.main_window.file_tree_handler.file_tree.keyPressEvent(event)
                # Check if the tree view handled the event (event.accepted())
                if event.isAccepted():
                    return True
                # If tree view didn't handle it, continue to keyboard handler manager
        # Only process with keyboard_handler_manager if focus is NOT on tree_container or file_tree
        if not (
            focused_widget == getattr(self.main_window, 'tree_container', None) or
            (hasattr(self.main_window, 'file_tree_handler') and 
             self.main_window.file_tree_handler.is_tree_initialized() and 
             hasattr(self.main_window.file_tree_handler, 'file_tree') and 
             focused_widget == self.main_window.file_tree_handler.file_tree)
        ):
            if hasattr(self.main_window, 'keyboard_handler_manager') and self.main_window.keyboard_handler_manager:
                if self.main_window.keyboard_handler_manager.handle_key_event(event):
                    event.accept()
                    return True
                # If keyboard handler didn't handle the event, ensure it's not accepted
                # so QAction shortcuts can work
                event.setAccepted(False)

        # Fallback to parent implementation if no handler processed the event
        super().keyPressEvent(event)
        return False
    
    def event(self, event):
        """Handle general events including gesture events and key events before shortcuts"""
        if hasattr(event, 'type') and event.type() == QEvent.Gesture:
            return self.main_window.gestureEvent(event)
        
        # Intercept E, H, PageUp, and PageDown keys before Qt processes QAction shortcuts
        if event.type() == QEvent.KeyPress and isinstance(event, QKeyEvent):
            # Handle Control+number keys for favorites (Ctrl+1 through Ctrl+9)
            # On macOS, Qt.MetaModifier is the actual Control key (not Command)
            # Qt.ControlModifier is the Command key (⌘) on macOS
            modifiers = event.modifiers()
            has_meta = bool(modifiers & Qt.MetaModifier)
            has_control = bool(modifiers & Qt.ControlModifier)
            has_shift = bool(modifiers & Qt.ShiftModifier)
            has_alt = bool(modifiers & Qt.AltModifier)
            key = event.key()
            
            # Delegate to main window's event handler for complex logic
            return self.main_window.event(event)
        
        return super().event(event)
    
    def eventFilter(self, obj, event):
        """Event filter to catch keyboard events when main window has NoFocus"""
        
        if event.type() == QEvent.KeyPress:
            
            # Only handle keyboard events if the main window doesn't have focus
            # This prevents double processing when the main window receives the event normally
            has_focus = self.main_window.hasFocus()
            if not has_focus:
                result = self.keyPressEvent(event)
                if result:
                    return True  # Event handled
                else:
                    return super().eventFilter(obj, event)
            else:
                return super().eventFilter(obj, event)
        return super().eventFilter(obj, event)
    
    def focusInEvent(self, event):
        """Handle focus in event"""
        super().focusInEvent(event)
    
    def focusOutEvent(self, event):
        """Handle focus out event"""
        super().focusOutEvent(event)
    
    def showEvent(self, event):
        """Handle window show event"""
        super().showEvent(event)
        # Ensure proper focus when window is shown - set immediately and also after short delay
        # This ensures menu keys work right away
        self.main_window._ensure_proper_focus()
        QTimer.singleShot(50, self.main_window._ensure_proper_focus)
    
    def hideEvent(self, event):
        """Handle window hide event"""
        super().hideEvent(event)
    
    def closeEvent(self, event):
        """Handle window close event"""
        self.main_window.message_handler.cleanup()
        
        from image_cache import cleanup_cache
        cleanup_cache()
        
        # Cleanup worker threads
        self.main_window.ensure_cleanup_before_exit()
        
        # Save window state
        self.main_window.config.update_setting('window_geometry', self.main_window.saveGeometry().data().hex())
        self.main_window.config.update_setting('window_state', self.main_window.saveState().data().hex())
        
        super().closeEvent(event)
    
    def resizeEvent(self, event):
        """Handle window resize events"""
        super().resizeEvent(event)
        
        # Update MAX_THUMBNAIL_SIZE based on new container dimensions
        self.main_window.update_max_thumbnail_size()
        
        # Reposition progress bars on resize
        if hasattr(self.main_window, '_position_progress_bars'):
            self.main_window._position_progress_bars()
        
        # Handle browse mode resize immediately for responsive behavior
        if self.main_window.current_view_mode == 'browse' and hasattr(self.main_window, 'current_pixmap') and self.main_window.current_pixmap:
            mw = self.main_window
            old_w = mw.cached_container_width
            old_h = mw.cached_container_height
            if hasattr(mw, 'image_container'):
                available_size = mw.get_effective_display_size()
                mw.image_container.resize(available_size)
            mw._handle_browse_viewport_resize_after_container_change(old_w, old_h)
            return  # Skip the delayed resize handling for browse mode
        
        # Delay resize handling to avoid multiple rapid calls for thumbnail mode
        if hasattr(self.main_window, '_resize_timer'):
            self.main_window._resize_timer.stop()
        else:
            self.main_window._resize_timer = QTimer()
            self.main_window._resize_timer.setSingleShot(True)
            self.main_window._resize_timer.timeout.connect(self.main_window._handle_resize)
        
        # Use longer delay for larger numbers of files to avoid overwhelming the system
        delay = 100 if len(self.main_window.displayed_images) <= 100 else 300
        self.main_window._resize_timer.start(delay)
    
    def connect_scroll_signals(self):
        """Connect scroll signals"""
        if hasattr(self.main_window, 'scroll_area') and self.main_window.scroll_area:
            self.main_window.scroll_area.verticalScrollBar().valueChanged.connect(self.main_window.on_scroll_changed)
    
    def on_scroll_changed(self, value):
        """Handle scroll change events"""
        # Delegate to main window method
        self.main_window.on_scroll_changed(value)
