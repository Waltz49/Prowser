#!/usr/bin/env python3
"""
Browse View Handler for Image Browser
Manages browse view operations, screen size calculations, and browse view-specific UI operations
Similar to SlideshowManager, manages browse view state and functionality
"""

# Standard library imports

# Third-party imports
from PySide6.QtCore import QSize, Qt, QTimer, QPointF
from PySide6.QtGui import QPixmap, QPainter, QColor
from PySide6.QtWidgets import QApplication, QGestureEvent

from config import effective_browse_border_color, effective_browse_transparency

# macOS-specific imports
try:
    from AppKit import NSScreen
    MACOS_SCREEN_AVAILABLE = True
except ImportError:
    MACOS_SCREEN_AVAILABLE = False
    NSScreen = None


def _draw_diamond_pattern(pixmap: QPixmap):
    """Draw a checkerboard pattern on the pixmap (grey on black).
    Optimized for performance using simple rectangle fills.
    """
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing, False)
    
    # Fill with black background
    painter.fillRect(pixmap.rect(), QColor(128, 128, 128))
    
    # Checkerboard pattern parameters
    # Each square is 16x16 pixels
    tile_size = 8
    
    # Grey color for checkerboard squares
    grey_color = QColor(96, 96, 96)
    
    width = pixmap.width()
    height = pixmap.height()
    
    # Draw checkerboard pattern efficiently using rectangles
    # Calculate how many tiles we need
    num_cols = (width // tile_size) + 2
    num_rows = (height // tile_size) + 2
    
    # Draw alternating squares
    for row in range(num_rows):
        for col in range(num_cols):
            # Alternate pattern: checkerboard
            if (row + col) % 2 == 0:
                x = col * tile_size
                y = row * tile_size
                painter.fillRect(x, y, tile_size, tile_size, grey_color)
    
    painter.end()


_ZOOM_GESTURE_NOTIFICATION_DEBOUNCE_MS = 300


class BrowseViewHandler:
    """Manages browse view functionality, extracted from ImageBrowserWindow.
    Similar to SlideshowManager, manages its own browse view state and operations.
    """
    
    def __init__(self, window):
        """Initialize browse view handler"""
        super().__setattr__('window', window)
        self.main_window = window
        self._zoom_gesture_notify_timer = QTimer(self.main_window)
        self._zoom_gesture_notify_timer.setSingleShot(True)
        self._zoom_gesture_notify_timer.setInterval(_ZOOM_GESTURE_NOTIFICATION_DEBOUNCE_MS)
        self._zoom_gesture_notify_timer.timeout.connect(self._flush_zoom_gesture_notification)
    
    def _flush_zoom_gesture_notification(self):
        mw = self.main_window
        if mw.status_notification:
            zoom_percent = int(mw.scale_factor * 100)
            mw.status_notification.show_message(f"Zoom: {zoom_percent}%", duration=1000)
    
    def reset_image_label_for_browse_view(self):
        """Reset the image label for browse view display"""
        if self.main_window.image_label:
            self.main_window.image_label.clear()
            self.main_window.image_label.setPixmap(QPixmap())
            self.main_window.current_pixmap = None
            self.main_window.scale_factor = 1.0
            self.main_window.scroll_x = 0
            self.main_window.scroll_y = 0
            self.main_window.browse_zoom_pinned = False
    
    def ensure_browse_view_focus(self):
        """Ensure proper focus for browse view keyboard event handling"""
        if self.main_window.current_view_mode == 'browse':
            # Don't steal focus - let Qt handle tab navigation naturally
            self.main_window.raise_()
            self.main_window.browse_view_input_ready = True
    
    def resize_browse_view_image_container(self):
        """Resize the image container in browse view mode to account for sidebar changes"""
        if self.main_window.current_view_mode == 'browse' and hasattr(self.main_window, 'image_container'):
            # Force layout update to ensure main_content_widget has correct size
            if hasattr(self.main_window, 'main_content_widget') and self.main_window.main_content_widget:
                self.main_window.main_content_widget.updateGeometry()
            if hasattr(self.main_window, 'main_splitter'):
                self.main_window.main_splitter.updateGeometry()
            
            mw = self.main_window
            old_w = mw.cached_container_width
            old_h = mw.cached_container_height
            available_size = self.get_effective_display_size()
            mw.image_container.resize(available_size)
            mw._handle_browse_viewport_resize_after_container_change(old_w, old_h)
    
    def center_image_label(self):
        """Center the image label in the container"""
        if not self.main_window.image_label:
            return
        
        # Center the image label
        self.main_window.image_label.setGeometry(0, 0, self.main_window.image_container.width(), self.main_window.image_container.height())
    
    def convert_cursor_to_image_coordinates(self, cursor_pos: QPointF) -> QPointF:
        """
        Convert cursor position from main window coordinates to coordinates relative to the image content.
        The cursor position is relative to the main window, but we need coordinates relative to the main content area.
        """
        if not self.main_window.image_label or not self.main_window.current_pixmap:
            return cursor_pos
        
        # Get the main content widget position relative to the main window
        if hasattr(self.main_window, 'main_content_widget') and self.main_window.main_content_widget:
            # Convert from main window coordinates to main content widget coordinates
            content_pos = self.main_window.main_content_widget.mapFromParent(cursor_pos.toPoint())
            content_relative_x = content_pos.x()
            content_relative_y = content_pos.y()
        else:
            # Fallback: assume cursor is already relative to content area
            content_relative_x = cursor_pos.x()
            content_relative_y = cursor_pos.y()
        
        # Get the available display area
        available_size = self.get_browse_paint_viewport_size()
        if available_size.width() < 200 or available_size.height() < 200:
            available_size = self.main_window.size()
        
        # If we're in fit-to-window mode (scale_factor <= 1.0), the image content is scaled and centered
        if self.main_window.scale_factor <= 1.0 and not self.main_window.is_actual_size:
            # Calculate the scaled image dimensions (same logic as in update_image_display)
            fit_scale_x = available_size.width() / self.main_window.current_pixmap.width()
            fit_scale_y = available_size.height() / self.main_window.current_pixmap.height()
            fit_scale = min(fit_scale_x, fit_scale_y)
            
            # Dimensions of the fitted image
            fitted_width = self.main_window.current_pixmap.width() * fit_scale
            fitted_height = self.main_window.current_pixmap.height() * fit_scale
            
            # Position of fitted image within the available area (centered)
            fitted_x = (available_size.width() - fitted_width) / 2
            fitted_y = (available_size.height() - fitted_height) / 2
            
            # Convert to coordinates relative to the fitted image
            image_relative_x = content_relative_x - fitted_x
            image_relative_y = content_relative_y - fitted_y
            
            # Clamp to image bounds
            image_relative_x = max(0, min(fitted_width, image_relative_x))
            image_relative_y = max(0, min(fitted_height, image_relative_y))
            
            # Convert back to coordinates relative to the available display area
            # The fitted image is centered in the available area (same as in zoom_at_point)
            display_relative_x = (available_size.width() - fitted_width) / 2 + image_relative_x
            display_relative_y = (available_size.height() - fitted_height) / 2 + image_relative_y
            
            return QPointF(display_relative_x, display_relative_y)
        else:
            # For zoomed mode, use the content-relative coordinates directly
            return QPointF(content_relative_x, content_relative_y)
    
    def refresh_browse_view_display(self):
        """Refresh browse view display"""
        self.main_window.pending_browse_view_refresh = False
        
        if self.main_window.current_view_mode == 'browse':
            current_size = self.main_window.size()
            if current_size != self.main_window.last_browse_view_size:
                self.main_window.last_browse_view_size = current_size
                self.main_window.update_image_display()
    
    def reset_browse_view_exit_tracking(self):
        """Reset browse view exit tracking state"""
        self.main_window.browse_view_exit_in_progress = False
    
    def enable_macos_fullscreen_button(self):
        """Enable macOS native fullscreen button"""
        self.main_window.showFullScreen()
    
    def toggle_fullscreen(self):
        """Toggle fullscreen mode"""
        if self.main_window.isFullScreen():
            self.main_window.showNormal()
        else:
            self.main_window.showFullScreen()
            # Force recalculation after entering fullscreen
            QTimer.singleShot(100, self.main_window.force_resize_recalculation)
            # Also ensure image container is resized if we're in fullscreen view mode
            if self.main_window.current_view_mode == 'browse' and hasattr(self.main_window, 'image_container'):
                QTimer.singleShot(150, lambda: self.main_window.image_container.resize(self.get_effective_display_size()))
        
        # Update macOS fullscreen checkbox state with a slight delay to ensure macOS Spaces state is available
        QTimer.singleShot(200, self.main_window.menu_manager.update_native_fullscreen_checkbox)
    
    def enter_true_fullscreen(self):
        """Enter true fullscreen mode"""
        self.main_window.showFullScreen()
    
    def get_physical_screen_size(self) -> QSize:
        """Get the physical screen size for actual size calculations"""
        try:
            if MACOS_SCREEN_AVAILABLE and NSScreen:
                screen = NSScreen.mainScreen()
                if screen:
                    frame_size = screen.frame().size
                    return QSize(int(frame_size.width), int(frame_size.height))
        except Exception:
            pass
        
        # Fallback: use QApplication primary screen
        try:
            app = QApplication.instance()
            if app and app.primaryScreen():
                screen_geometry = app.primaryScreen().geometry()
                return QSize(screen_geometry.width(), screen_geometry.height())
        except Exception:
            pass
        
        # Final fallback: use window size (not ideal but better than nothing)
        return self.main_window.size()
    
    def get_effective_display_size(self) -> QSize:
        """Get the effective display size, accounting for status bar visibility, file tree, and right sidebar"""
        # In fullscreen mode, always use the actual window size to correctly handle
        # cases where macOS spaces are shared with other applications (side-by-side)
        # Also avoids issues with widget sizes not being updated yet after fullscreen transition
        if self.main_window.current_view_mode == 'browse':
            # In fullscreen mode, use window size directly to avoid stale widget sizes
            if self.main_window.isFullScreen():
                window_size = self.main_window.size()
                window_width = window_size.width()
                window_height = window_size.height()
                
                # Account for right sidebar if visible (should be hidden in browse mode, but check anyway)
                if hasattr(self.main_window, 'right_sidebar') and self.main_window.right_sidebar.isVisible():
                    window_width -= self.main_window.right_sidebar.width()
                
                # Account for status bar height if it's visible
                if self.main_window.status_bar_visible:
                    status_bar_height = self.main_window.status_bar.height() if self.main_window.status_bar.isVisible() else 0
                    window_height -= status_bar_height
                
                return QSize(window_width, window_height)
            
            # In windowed browse mode, use main content widget size to account for sidebars.
            # Do not subtract status bar height: QMainWindow already sizes the central widget
            # (and thus main_content_widget) above the status bar. Subtracting again made the
            # browse image area too short, so after toggling the status bar on the pixmap was
            # drawn for the wrong height until the next pan/zoom/scroll repainted the view.
            if hasattr(self.main_window, 'main_content_widget') and self.main_window.main_content_widget:
                content_size = self.main_window.main_content_widget.size()
                return QSize(content_size.width(), content_size.height())
            
            # Fallback to window size
            window_size = self.main_window.size()
            window_width = window_size.width()
            window_height = window_size.height()
            
            # Account for right sidebar if visible
            if hasattr(self.main_window, 'right_sidebar') and self.main_window.right_sidebar.isVisible():
                window_width -= self.main_window.right_sidebar.width()
            
            # Account for status bar height if it's visible
            if self.main_window.status_bar_visible:
                status_bar_height = self.main_window.status_bar.height() if self.main_window.status_bar.isVisible() else 0
                window_height -= status_bar_height
            return QSize(window_width, window_height)
        
        # Use the main content widget size to account for file tree space (thumbnail mode)
        if hasattr(self.main_window, 'main_content_widget') and self.main_window.main_content_widget:
            # Use scroll area viewport for actual visible size - accounts for both left
            # (combined) sidebar AND right (Information) sidebar. Viewport is the visible
            # thumbnail area; Qt updates it when the splitter resizes main content.
            if (hasattr(self.main_window, 'thumbnail_container') and
                    hasattr(self.main_window.thumbnail_container, 'scroll_area')):
                scroll_area = self.main_window.thumbnail_container.scroll_area
                viewport = scroll_area.viewport()
                canvas_width = viewport.width()
                canvas_height = viewport.height()
                
                if self.main_window.status_bar_visible:
                    status_bar_height = self.main_window.status_bar.height() if self.main_window.status_bar.isVisible() else 0
                    canvas_height -= status_bar_height
                if canvas_width > 0 and canvas_height > 0:
                    return QSize(canvas_width, canvas_height)
            
            # Fallback: canvas viewport if scroll_area not available
            content_size = self.main_window.main_content_widget.size()
            if hasattr(self.main_window, 'thumbnail_container'):
                canvas = self.main_window.thumbnail_container.canvas
                if hasattr(canvas, 'get_viewport_width') and hasattr(canvas, 'get_viewport_height'):
                    canvas_width = canvas.get_viewport_width()
                    canvas_height = canvas.get_viewport_height()
                    if self.main_window.status_bar_visible:
                        status_bar_height = self.main_window.status_bar.height() if self.main_window.status_bar.isVisible() else 0
                        canvas_height -= status_bar_height
                    return QSize(canvas_width, canvas_height)
            
            # Account for status bar height if it's visible
            if self.main_window.status_bar_visible:
                status_bar_height = self.main_window.status_bar.height() if self.main_window.status_bar.isVisible() else 0
                return QSize(content_size.width(), content_size.height() - status_bar_height)
            return QSize(content_size.width(), content_size.height())
        
        # Fallback: use screen/window size for older behavior
        try:
            if MACOS_SCREEN_AVAILABLE and NSScreen:
                screen = NSScreen.mainScreen()
                if screen:
                    frame_size = screen.frame().size
                    # Account for status bar height if it's visible
                    if self.main_window.status_bar_visible:
                        status_bar_height = self.main_window.status_bar.height() if self.main_window.status_bar.isVisible() else 0
                        return QSize(int(frame_size.width), int(frame_size.height) - status_bar_height)
                    return QSize(int(frame_size.width), int(frame_size.height))
        except Exception:
            pass
        
        # Fallback: use window size and account for status bar
        if self.main_window.status_bar_visible:
            status_bar_height = self.main_window.status_bar.height() if self.main_window.status_bar.isVisible() else 0
            window_size = self.main_window.size()
            return QSize(window_size.width(), window_size.height() - status_bar_height)
        
        # Default fallback
        return QSize(1920, 1080)

    def get_browse_paint_viewport_size(self) -> QSize:
        """Pixel size of the browse image area for painting and zoom math.
        Prefer image_container geometry (matches layout during live window resize);
        fall back to get_effective_display_size() before layout is ready."""
        mw = self.main_window
        if mw.current_view_mode == 'browse' and hasattr(mw, 'image_container') and mw.image_container:
            s = mw.image_container.size()
            if s.width() >= 2 and s.height() >= 2:
                return s
        return self.get_effective_display_size()

    def handle_mouse_press(self, event):
        """Handle mouse press for dragging/panning in browse mode"""
        mw = self.main_window
        if mw.current_view_mode != 'browse':
            return False
        
        cursor_manager = mw.cursor_manager
        btn = event.button()
        if cursor_manager and cursor_manager.is_active():
            cursor_manager.on_mouse_activity()

        if btn == Qt.LeftButton and self.can_pan_image():
            mw.is_dragging = True
            mw.drag_start_pos = event.position().toPoint()
            mw.drag_start_scroll_x = mw.scroll_x
            mw.drag_start_scroll_y = mw.scroll_y
            (cursor_manager.set_cursor if cursor_manager else mw.setCursor)(Qt.ClosedHandCursor)
            return True
        elif btn == Qt.RightButton:
            mw.view_manager.close_browse_view()
            return True
        
        return False

    def handle_mouse_move(self, event):
        """Handle mouse movement for dragging panned images in browse mode"""
        mw = self.main_window
        if mw.current_view_mode != 'browse':
            return False
        
        # Notify cursor manager of mouse activity
        if mw.cursor_manager:
            mw.cursor_manager.on_mouse_activity()
        
        if mw.is_dragging:
            if mw.drag_start_pos is not None:
                # Calculate drag distance
                current_pos = event.position().toPoint()
                delta_x = current_pos.x() - mw.drag_start_pos.x()
                delta_y = current_pos.y() - mw.drag_start_pos.y()
                
                # Apply drag offset to scroll position
                mw.scroll_x = mw.drag_start_scroll_x + delta_x
                mw.scroll_y = mw.drag_start_scroll_y + delta_y
                
                # Update image position
                self.apply_pan_offset()
                return True
        else:
            # Show appropriate cursor when hovering over pannable image
            if self.can_pan_image() and not mw.is_dragging:
                if mw.cursor_manager:
                    mw.cursor_manager.set_cursor(Qt.OpenHandCursor)
                else:
                    mw.setCursor(Qt.OpenHandCursor)
                return True
        
        return False

    def handle_mouse_release(self, event):
        """Handle mouse release to stop dragging in browse mode"""
        mw = self.main_window
        if mw.current_view_mode != 'browse':
            return False
        
        # Notify cursor manager of mouse activity
        if mw.cursor_manager:
            mw.cursor_manager.on_mouse_activity()
        
        if event.button() == Qt.LeftButton:
            if mw.is_dragging:
                mw.is_dragging = False
                mw.drag_start_pos = None
                # Set cursor based on whether image is pannable
                if self.can_pan_image():
                    if mw.cursor_manager:
                        mw.cursor_manager.set_cursor(Qt.OpenHandCursor)
                    else:
                        mw.setCursor(Qt.OpenHandCursor)
                else:
                    if mw.cursor_manager:
                        mw.cursor_manager.set_cursor(Qt.ArrowCursor)
                    else:
                        mw.setCursor(Qt.ArrowCursor)
                return True
        
        return False

    def handle_gesture_event(self, event: QGestureEvent):
        """Handle gesture events, particularly pinch gestures for trackpad zoom"""
        mw = self.main_window
        # Notify cursor manager of mouse activity only in browse mode
        if (mw.cursor_manager and 
            mw.current_view_mode == 'browse' and 
            mw.cursor_manager.is_active()):
            mw.cursor_manager.on_mouse_activity()
        
        pinch = event.gesture(Qt.PinchGesture)
        if pinch and mw.current_view_mode == 'browse':
            if pinch.state() == Qt.GestureStarted:
                # Store the initial gesture position for cursor-aware zoom
                mw.zoom_center_point = pinch.centerPoint()
                self._zoom_gesture_notify_timer.stop()
                
            elif pinch.state() == Qt.GestureUpdated:
                # Get scale factor from pinch gesture
                scale_change = pinch.scaleFactor()
                
                # Apply zoom with scale change
                new_scale = mw.scale_factor * scale_change
                
                # Clamp the scale factor to reasonable limits
                new_scale = max(0.1, min(8.0, new_scale))
                
                # Only update if scale actually changed significantly
                if abs(new_scale - mw.scale_factor) > 0.01:
                    # Apply cursor-aware zoom
                    self.zoom_at_point(new_scale, mw.zoom_center_point)
                    
                    # Debounce status notification (pinch sends many updates)
                    if mw.status_notification:
                        self._zoom_gesture_notify_timer.start()
                    if mw.filename_visible:
                        mw.right_sidebar.show_image_info_overlay()
            
            elif pinch.state() in (Qt.GestureFinished, Qt.GestureCanceled):
                self._zoom_gesture_notify_timer.stop()
                if mw.status_notification:
                    self._flush_zoom_gesture_notification()
            
            event.accept()
            return True
        
        return False

    def can_pan_image(self) -> bool:
        """Check if the displayed image is larger than the viewport and can be panned"""
        mw = self.main_window
        if not mw.current_pixmap:
            return False
        
        # Get the available display area
        available_size = self.get_browse_paint_viewport_size()
        
        # Use transformed pixmap if available, otherwise use original
        source_pixmap = mw.temp_transformed_pixmap or mw.current_pixmap
        
        # Calculate the displayed image size (after scaling)
        displayed_width = int(source_pixmap.width() * mw.scale_factor)
        displayed_height = int(source_pixmap.height() * mw.scale_factor)
        
        can_pan = (displayed_width > available_size.width() or 
                   displayed_height > available_size.height())
        
        return can_pan

    def fit_image_to_canvas_width(self):
        """Scale browse image so its width matches the paint viewport; align to top when taller than viewport."""
        mw = self.main_window
        if mw.current_view_mode != 'browse' or not mw.current_pixmap:
            return
        source_pixmap = mw.apply_transformations_to_pixmap(mw.current_pixmap)
        available_size = self.get_browse_paint_viewport_size()
        if available_size.width() < 1 or source_pixmap.width() < 1:
            return
        mw.is_actual_size = False
        mw.browse_zoom_pinned = True
        mw.scale_factor = available_size.width() / float(source_pixmap.width())
        mw.scroll_x = 0
        tw = int(source_pixmap.width() * mw.scale_factor)
        th = int(source_pixmap.height() * mw.scale_factor)
        scaled = source_pixmap.scaled(
            QSize(tw, th),
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation,
        )
        max_pan_y = max(0, (scaled.height() - available_size.height()) // 2)
        mw.scroll_y = max_pan_y
        mw.update_image_display()
        if hasattr(mw, 'update_status_bar_fit_mode'):
            mw.update_status_bar_fit_mode()
        if mw.filename_visible:
            mw.right_sidebar.show_image_info_overlay()
    
    def get_visible_source_rect(self):
        """
        Get the visible portion of the image in source (transformed) pixmap coordinates.
        Returns (x, y, width, height) tuple, or None if not in browse mode or no image.
        Used when wallpaper uses visible browse pixels - captures what the user actually sees.
        """
        mw = self.main_window
        if not mw.current_pixmap or mw.current_view_mode != 'browse':
            return None
        
        source_pixmap = mw.temp_transformed_pixmap
        if source_pixmap is None:
            source_pixmap = mw.apply_transformations_to_pixmap(mw.current_pixmap)
        
        available_size = self.get_browse_paint_viewport_size()
        src_w = source_pixmap.width()
        src_h = source_pixmap.height()
        
        if not self.can_pan_image():
            # Full image is visible
            return (0, 0, src_w, src_h)
        
        # Pannable: compute visible rect in scaled coords, then convert to source
        target_width = int(src_w * mw.scale_factor)
        target_height = int(src_h * mw.scale_factor)
        scaled_w = target_width
        scaled_h = target_height
        
        src_x = max(0, (scaled_w - available_size.width()) // 2 - mw.scroll_x)
        src_y = max(0, (scaled_h - available_size.height()) // 2 - mw.scroll_y)
        src_width = min(scaled_w - src_x, available_size.width())
        src_height = min(scaled_h - src_y, available_size.height())
        
        # Convert from scaled coords to source coords
        scale = mw.scale_factor
        source_x = int(src_x / scale)
        source_y = int(src_y / scale)
        source_width = int(src_width / scale)
        source_height = int(src_height / scale)
        
        # Clamp to source bounds
        source_x = max(0, min(src_w - 1, source_x))
        source_y = max(0, min(src_h - 1, source_y))
        source_width = max(1, min(src_w - source_x, source_width))
        source_height = max(1, min(src_h - source_y, source_height))
        
        return (source_x, source_y, source_width, source_height)
    
    def apply_pan_offset(self):
        """Apply pan offset to image position by redrawing the visible portion"""
        mw = self.main_window
        if not mw.current_pixmap:
            return
        
        # Check if panning is needed (image larger than viewport)
        if not self.can_pan_image():
            # Image fits in viewport - display directly without panning
            if hasattr(mw, 'image_label'):
                # Use the transformed pixmap (should always be available at this point)
                source_pixmap = mw.temp_transformed_pixmap
                if source_pixmap is None:
                    # Fallback: apply transformations if temp pixmap is missing
                    source_pixmap = mw.apply_transformations_to_pixmap(mw.current_pixmap)
                
                if mw.scale_factor == 1.0:
                    # Actual size, fits in viewport
                    mw.image_label.setPixmap(source_pixmap)
                else:
                    # Scaled down to fit, display directly
                    available_size = self.get_browse_paint_viewport_size()
                    target_width = int(source_pixmap.width() * mw.scale_factor)
                    target_height = int(source_pixmap.height() * mw.scale_factor)
                    scaled_pixmap = source_pixmap.scaled(
                        QSize(target_width, target_height),
                        Qt.KeepAspectRatio,
                        Qt.SmoothTransformation
                    )
                    mw.image_label.setPixmap(scaled_pixmap)
            return
        
        # Skip if slideshow2 is active to prevent interference
        if (hasattr(mw, 'image_label') and hasattr(mw.image_label, 'slideshow2_active') 
            and mw.image_label.slideshow2_active):
            return
        
        # Get the available display area using the same logic as update_image_display
        available_size = self.get_browse_paint_viewport_size()
        
        # Pan limits must match the viewport used for src_* / dst_* below. Using screen size
        # (or any size larger than the paint area) clamps scroll too tightly in windowed mode,
        # so the top/bottom/left/right edges of a zoomed image cannot be reached.
        
        # Use transformed pixmap if available, otherwise apply transformations
        source_pixmap = mw.temp_transformed_pixmap
        if source_pixmap is None:
            # Fallback: apply transformations if temp pixmap is missing
            source_pixmap = mw.apply_transformations_to_pixmap(mw.current_pixmap)
        
        # Calculate the scaled image size
        # Normal scaling: scale based on original image dimensions
        target_width = int(source_pixmap.width() * mw.scale_factor)
        target_height = int(source_pixmap.height() * mw.scale_factor)
        
        # Scale the source pixmap to the target size
        scaled_pixmap = source_pixmap.scaled(
            QSize(target_width, target_height),
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation
        )
        
        # Calculate pan limits to prevent panning beyond image bounds
        max_pan_x = max(0, (scaled_pixmap.width() - available_size.width()) // 2)
        max_pan_y = max(0, (scaled_pixmap.height() - available_size.height()) // 2)
        
        # Clamp pan values
        mw.scroll_x = max(-max_pan_x, min(max_pan_x, mw.scroll_x))
        mw.scroll_y = max(-max_pan_y, min(max_pan_y, mw.scroll_y))
        
        display_pixmap = QPixmap(available_size)
        s = mw.config.load_settings()
        brgb = effective_browse_border_color(s)
        display_pixmap.fill(QColor(brgb[0], brgb[1], brgb[2]))
        transparency_color_rgb, use_diamonds = effective_browse_transparency(s)
        transparency_color = QColor(transparency_color_rgb[0], transparency_color_rgb[1], transparency_color_rgb[2])
        
        # Calculate the source rectangle from the scaled image
        src_x = max(0, (scaled_pixmap.width() - available_size.width()) // 2 - mw.scroll_x)
        src_y = max(0, (scaled_pixmap.height() - available_size.height()) // 2 - mw.scroll_y)
        src_width = min(scaled_pixmap.width() - src_x, available_size.width())
        src_height = min(scaled_pixmap.height() - src_y, available_size.height())
        
        # Calculate destination position (center the cropped image if it's smaller than display area)
        dst_x = max(0, (available_size.width() - src_width) // 2)
        dst_y = max(0, (available_size.height() - src_height) // 2)
        
        # Get the visible portion of the scaled image
        visible_scaled_pixmap = scaled_pixmap.copy(src_x, src_y, src_width, src_height)
        
        # Create composited pixmap - SIZE OF THE SCALED IMAGE (not screen size)
        composited_pixmap = QPixmap(visible_scaled_pixmap.size())
        # Fill with black first so pattern is visible
        composited_pixmap.fill(QColor(0, 0, 0))
        
        # Fill with diamond pattern or transparency color for transparent areas within the image
        if use_diamonds:
            _draw_diamond_pattern(composited_pixmap)
        else:
            composited_pixmap.fill(transparency_color)
        
        # Draw the image on top - transparent pixels will show diamond pattern or transparency_color
        # Check if the source pixmap has alpha channel
        source_has_alpha = visible_scaled_pixmap.toImage().hasAlphaChannel()
        composite_painter = QPainter(composited_pixmap)
        composite_painter.setRenderHint(QPainter.Antialiasing)
        if source_has_alpha:
            # Use SourceOver to composite transparent pixels onto the pattern/color background
            composite_painter.setCompositionMode(QPainter.CompositionMode_SourceOver)
        else:
            # No alpha channel - just draw directly (will cover the pattern)
            composite_painter.setCompositionMode(QPainter.CompositionMode_SourceOver)
        composite_painter.drawPixmap(0, 0, visible_scaled_pixmap)
        composite_painter.end()
        
        # Paint the composited pixmap onto the display pixmap (margins use browse border color)
        painter = QPainter(display_pixmap)
        painter.setCompositionMode(QPainter.CompositionMode_SourceOver)
        painter.drawPixmap(dst_x, dst_y, composited_pixmap)
        painter.end()
        
        # Set the resulting pixmap to the label
        mw.image_label.setPixmap(display_pixmap)
        
        # Don't clean up temporary transformed pixmap immediately - it might be needed for subsequent pan operations
        # The pixmap will be cleaned up when update_image_display is called again

    def zoom_at_point(self, new_scale: float, zoom_point: QPointF):
        """
        Zoom the image while keeping the pixel under zoom_point stationary.
        """
        mw = self.main_window
        if not mw.current_pixmap or new_scale <= 0:
            return
        
        # Get available display area - use effective display size to account for tree view
        available_size = self.get_browse_paint_viewport_size()
        if available_size.width() < 200 or available_size.height() < 200:
            available_size = mw.size()
        
        # Store old scale factor
        old_scale = mw.scale_factor
        
        # If we're transitioning from fit-to-window to zoomed mode
        if old_scale == 1.0 and new_scale != 1.0:
            # Calculate the image coordinates corresponding to the zoom point
            # First, get the current scaled image dimensions
            fit_scale_x = available_size.width() / mw.current_pixmap.width()
            fit_scale_y = available_size.height() / mw.current_pixmap.height()
            fit_scale = min(fit_scale_x, fit_scale_y)
            
            # Dimensions of the fitted image
            fitted_width = mw.current_pixmap.width() * fit_scale
            fitted_height = mw.current_pixmap.height() * fit_scale
            
            # Position of fitted image (centered)
            fitted_x = (available_size.width() - fitted_width) / 2
            fitted_y = (available_size.height() - fitted_height) / 2
            
            # Convert zoom point from screen coordinates to image coordinates
            relative_x = (zoom_point.x() - fitted_x) / fitted_width
            relative_y = (zoom_point.y() - fitted_y) / fitted_height
            
            # Clamp to image bounds
            relative_x = max(0, min(1, relative_x))
            relative_y = max(0, min(1, relative_y))
            
            # Calculate where this point should be after zoom
            new_scale_factor = new_scale
            new_image_width = mw.current_pixmap.width() * new_scale_factor
            new_image_height = mw.current_pixmap.height() * new_scale_factor
            
            # Calculate the scroll offset needed to keep the zoom point stationary
            target_x = relative_x * new_image_width
            target_y = relative_y * new_image_height
            
            # Calculate scroll position to keep zoom point at its screen position
            mw.scroll_x = -(zoom_point.x() - target_x + (new_image_width - available_size.width()) / 2)
            mw.scroll_y = -(zoom_point.y() - target_y + (new_image_height - available_size.height()) / 2)
            
        elif old_scale != 1.0 and new_scale != 1.0:
            # Both old and new are zoomed - adjust scroll to maintain zoom point
            scale_ratio = new_scale / old_scale
            
            # Get current image dimensions
            old_image_width = mw.current_pixmap.width() * old_scale
            old_image_height = mw.current_pixmap.height() * old_scale
            
            # Calculate the image coordinate under the zoom point
            image_center_x = (old_image_width - available_size.width()) / 2 - mw.scroll_x
            image_center_y = (old_image_height - available_size.height()) / 2 - mw.scroll_y
            
            point_in_image_x = image_center_x + zoom_point.x()
            point_in_image_y = image_center_y + zoom_point.y()
            
            # Scale the image coordinates
            new_point_in_image_x = point_in_image_x * scale_ratio
            new_point_in_image_y = point_in_image_y * scale_ratio
            
            # Calculate new scroll position to keep the point stationary
            new_image_width = mw.current_pixmap.width() * new_scale
            new_image_height = mw.current_pixmap.height() * new_scale
            
            new_image_center_x = (new_image_width - available_size.width()) / 2
            new_image_center_y = (new_image_height - available_size.height()) / 2
            
            mw.scroll_x = -(new_point_in_image_x - zoom_point.x() - new_image_center_x)
            mw.scroll_y = -(new_point_in_image_y - zoom_point.y() - new_image_center_y)
            
        elif new_scale == 1.0:
            # Zooming back to fit-to-window
            mw.scroll_x = 0
            mw.scroll_y = 0
        
        # Update scale factor and display
        scale_changed = abs(new_scale - old_scale) > 1e-6
        mw.scale_factor = new_scale
        if scale_changed:
            mw.browse_zoom_pinned = True
            mw.is_actual_size = False
        mw.update_image_display()
        
        # Update status bar sections
        if hasattr(mw, 'update_status_bar_fit_mode'):
            mw.update_status_bar_fit_mode()

    def zoom_in(self):
        """Zoom in on the image"""
        mw = self.main_window
        new_scale = min(8.0, mw.scale_factor * 1.2)
        mw.is_actual_size = False  # Manual zoom disables actual size mode
        # Zoom at center of screen
        center_point = QPointF(mw.width() / 2, mw.height() / 2)
        self.zoom_at_point(new_scale, center_point)
        if mw.filename_visible:
            mw.right_sidebar.show_image_info_overlay()

    def zoom_out(self):
        """Zoom out from the image"""
        mw = self.main_window
        new_scale = max(0.2, mw.scale_factor / 1.2)
        mw.is_actual_size = False  # Manual zoom disables actual size mode
        # Zoom at center of screen
        center_point = QPointF(mw.width() / 2, mw.height() / 2)
        self.zoom_at_point(new_scale, center_point)
        if mw.filename_visible:
            mw.right_sidebar.show_image_info_overlay()

    def toggle_actual_size(self):
        """Toggle between actual size and fit-to-window display"""
        mw = self.main_window
        if not mw.current_pixmap:
            return
        
        mw.browse_zoom_pinned = False
        
        # Toggle the actual size setting
        mw.is_actual_size = not mw.is_actual_size
        
        # Save the setting
        mw.config.update_setting('browse_view_actual_size', mw.is_actual_size)
        
        # Apply the new display mode
        if hasattr(mw, 'apply_current_display_mode'):
            mw.apply_current_display_mode()
        
        # Show status notification
        if mw.status_notification:
            if mw.is_actual_size:
                mw.status_notification.show_message("Actual size mode", duration=1500)
            else:
                mw.status_notification.show_message("Fit to window mode", duration=1500)
        
        # Update status bar sections
        if hasattr(mw, 'update_status_bar_fit_mode'):
            mw.update_status_bar_fit_mode()
        if mw.filename_visible:
            mw.right_sidebar.show_image_info_overlay()

