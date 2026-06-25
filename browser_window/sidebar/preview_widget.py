#!/usr/bin/env python3
"""
Preview Widget - Shows a preview of the currently active image
"""

import os
from typing import Optional
from PySide6.QtCore import Qt, QSize, QRect, QTimer
from PySide6.QtGui import QPainter, QPixmap, QImage, QFont, QColor, QPen, QMouseEvent
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QScrollArea
from theme.theme_service import get_active_theme


class ClickableImageLabel(QLabel):
    """QLabel that handles mouse clicks to open the image in browse view"""
    
    def __init__(self, main_window, parent=None):
        super().__init__(parent)
        self.main_window = main_window
        # Set cursor to pointer to indicate clickability
        self.setCursor(Qt.PointingHandCursor)
    
    def mousePressEvent(self, event: QMouseEvent):
        """Handle mouse click - open image in browse view (same as F key)"""
        if event.button() == Qt.LeftButton:
            # Only handle single clicks, not double clicks
            if hasattr(self.main_window, 'view_mode_manager') and self.main_window.view_mode_manager:
                # Open current image in browse view (same as pressing F key)
                self.main_window.view_mode_manager.open_current_browse_view()
        super().mousePressEvent(event)


class PreviewWidget(QWidget):
    """Widget that displays a preview of the currently active image"""
    
    def __init__(self, main_window, parent=None):
        super().__init__(parent)
        self.main_window = main_window
        self.preview_visible = False
        self.fit_mode = True  # True for best fit, False for actual size
        self.current_image_path = None
        self.current_pixmap = None
        self.scale_factor = 1.0
        
        self.setup_ui()
        
    def setup_ui(self):
        """Setup the preview widget UI"""
        self.setMinimumWidth(250)
        # Dynamically set max width based on main window width minus thumbnail column
        if self.main_window is not None and hasattr(self.main_window, 'width'):
            main_width = self.main_window.width()
            # Check if thumbnail_container exists (it's created later in initialization)
            if hasattr(self.main_window, 'thumbnail_container'):
                width_of_one_column_of_thumbnails = self.main_window.current_thumbnail_size + self.main_window.thumbnail_container.HORIZONTAL_SPACING + self.main_window.thumbnail_container.HIGHLIGHT_BORDER_WIDTH
                max_width = int((main_width - width_of_one_column_of_thumbnails) * 0.9)
            else:
                # Fallback to 70% of main window width if thumbnail_container not yet created
                max_width = int(main_width * 0.7)
            self.setMaximumWidth(max_width)
        else:
            self.setMaximumWidth(900)
        
        # Main layout
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        # Scroll area for the image
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.scroll_area.setStyleSheet("")
        
        # Image label (clickable to open image in browse view)
        self.image_label = ClickableImageLabel(self.main_window)
        self.image_label.setAlignment(Qt.AlignTop | Qt.AlignHCenter)
        self.image_label.setStyleSheet("")
        self.image_label.setText("No image selected")
        
        self.scroll_area.setWidget(self.image_label)
        layout.addWidget(self.scroll_area)
        self.refresh_theme_styles()

    def preferred_content_height(self, client_width: int) -> int:
        """Height needed to show the preview image at fit-to-width (no vertical scroll)."""
        width = max(client_width, 1)
        if self.current_pixmap and not self.current_pixmap.isNull():
            pw = self.current_pixmap.width()
            ph = self.current_pixmap.height()
            if pw > 0:
                scale = min(width / pw, 1.0)
                return int(ph * scale) + 10
        return self.image_label.sizeHint().height() + 4

    def refresh_theme_styles(self):
        """Apply active theme colors to preview shell."""
        th = get_active_theme()
        bg_hex = th.sidebar_background_color_hex
        text_hex = th.sidebar_text_color_hex
        self.scroll_area.setStyleSheet(f"QScrollArea {{ background-color: {bg_hex}; }}")
        self.image_label.setStyleSheet(f"background-color: {bg_hex}; color: {text_hex};")
        
    def toggle_visibility(self):
        """Toggle the visibility of the preview widget"""
        self.preview_visible = not self.is_visible()
        if self.preview_visible:
            self.update_preview()
        return self.is_visible()
        
    def toggle_fit_mode(self):
        """Toggle between fit and actual size modes"""
        self.fit_mode = not self.fit_mode
        if self.is_visible():
            self.update_preview()
            
    def reset_state(self):
        """Reset the preview widget state - useful when transitioning between view modes"""
        self.current_image_path = None
        self.current_pixmap = None
        self.fit_mode = True  # Preview should always fit; never use actual size
        # Don't reset preview_visible flag as it should be managed by the UI state
            
    def update_preview(self, force=False):
        """Update the preview with the current active image"""
        
        # Always update internal state when forced, even if not visible
        # This ensures the preview is ready when it becomes visible again
        if not self.is_visible() and not force:
            return
            
        # Get the current active image
        current_image_path = self.get_current_image_path()
        
        if not current_image_path or not os.path.exists(current_image_path):
            self.image_label.setText("No image selected")
            self.current_image_path = None
            self.current_pixmap = None
            return
        
        # Skip reloading if image path hasn't changed (performance optimization)
        if not force and getattr(self, 'current_image_path', None) == current_image_path:
            # Image path unchanged, no need to reload
            return
            
        # Load the image with EXIF correction
        try:
            # Try to load with EXIF correction first
            try:
                from exif.exif_image_loader import load_image_with_exif_correction
                # Get ignore_exif_rotation from main_window (cached) instead of loading config every time
                ignore_exif = getattr(self.main_window, 'ignore_exif_rotation', False)
                self.current_pixmap = load_image_with_exif_correction(current_image_path, ignore_exif=ignore_exif)
                if self.current_pixmap is None or self.current_pixmap.isNull():
                    # Fallback to direct loading if EXIF loader fails
                    image = QImage(current_image_path)
                    if image.isNull():
                        self.image_label.setText("Invalid image")
                        return
                    self.current_pixmap = QPixmap.fromImage(image)
            except ImportError:
                # Fallback to direct loading if exif_image_loader not available
                image = QImage(current_image_path)
                if image.isNull():
                    self.image_label.setText("Invalid image")
                    return
                self.current_pixmap = QPixmap.fromImage(image)
            
            if self.current_pixmap.isNull():
                self.image_label.setText("Invalid image")
                return
                
            self.current_image_path = current_image_path
            
            # Update display
            self._update_image_display()
            
        except Exception as e:
            self.image_label.setText(f"Error loading image")
            
    def _update_image_display(self):
        """Update the image display based on current mode"""
        if not self.current_pixmap:
            return
        
        # Apply transformations if they exist for this image
        display_pixmap = self.current_pixmap
        if (hasattr(self.main_window, 'apply_transformations_to_pixmap') and 
            self.current_image_path):
            display_pixmap = self.main_window.apply_transformations_to_pixmap(
                self.current_pixmap, self.current_image_path)
            
        if self.fit_mode:
            # Best fit mode - scale to fit within the scroll area
            # Get the actual viewport size (content area) instead of scroll area size
            viewport_size = self.scroll_area.viewport().size()
            available_width = viewport_size.width() - 10  # Small margin for padding
            available_height = viewport_size.height() - 10  # Small margin for padding
            
            pixmap_size = display_pixmap.size()
            
            # Calculate scale factor to fit
            scale_x = available_width / pixmap_size.width()
            scale_y = available_height / pixmap_size.height()
            self.scale_factor = min(scale_x, scale_y, 1.0)  # Don't scale up
            
            scaled_size = QSize(
                int(pixmap_size.width() * self.scale_factor),
                int(pixmap_size.height() * self.scale_factor)
            )
            
            scaled_pixmap = display_pixmap.scaled(
                scaled_size, 
                Qt.KeepAspectRatio, 
                Qt.SmoothTransformation
            )
            
        else:
            # Actual size mode
            self.scale_factor = 1.0
            scaled_pixmap = display_pixmap
            
        self.image_label.setPixmap(scaled_pixmap)
        
    def get_current_image_path(self):
        """Get the path of the currently active image"""
        if not hasattr(self.main_window, 'displayed_images') or not self.main_window.displayed_images:
            return None
            
        if not hasattr(self.main_window, 'highlight_index'):
            return None
            
        highlight_index = self.main_window.highlight_index
        if 0 <= highlight_index < len(self.main_window.displayed_images):
            image_path = self.main_window.displayed_images[highlight_index]
            return image_path
            
        return None
        
    def resizeEvent(self, event):
        """Handle resize events to update image display and max width"""
        super().resizeEvent(event)
        
        # Update max width based on current main window width
        if self.main_window is not None and hasattr(self.main_window, 'width'):
            main_width = self.main_window.width()
            # Check if thumbnail_container exists (it's created later in initialization)
            if hasattr(self.main_window, 'thumbnail_container'):
                width_of_one_column_of_thumbnails = self.main_window.current_thumbnail_size + self.main_window.thumbnail_container.HORIZONTAL_SPACING + self.main_window.thumbnail_container.HIGHLIGHT_BORDER_WIDTH
                max_width = int((main_width - width_of_one_column_of_thumbnails) * 0.9)
            else:
                # Fallback to 70% of main window width if thumbnail_container not yet created
                max_width = int(main_width * 0.7)
            self.setMaximumWidth(max_width)
        
        # Check actual visibility - use combined sidebar state if available, otherwise check widget visibility
        # This ensures resize works even when preview_visible flag hasn't been set yet (e.g., on first show)
        is_actually_visible = False
        if hasattr(self.main_window, 'combined_sidebar') and self.main_window.combined_sidebar:
            is_actually_visible = self.main_window.combined_sidebar.is_preview_visible() and self.isVisible()
        else:
            is_actually_visible = self.preview_visible and self.isVisible()
        
        if is_actually_visible and self.current_pixmap:
            # Delay the update to avoid excessive redraws during resize
            QTimer.singleShot(10, self._update_image_display)
            
    def is_visible(self):
        """Check if the preview is currently visible"""
        # Check if the widget is actually visible in the UI
        widget_visible = self.isVisible()
        self.preview_visible = widget_visible
        
        # Also check parent visibility
        if hasattr(self.main_window, 'combined_sidebar'):
            sidebar_visible = self.main_window.combined_sidebar.isVisible()
            preview_tab_visible = self.main_window.combined_sidebar.is_preview_visible()
        
        return self.preview_visible
        # # Check if we're inside a combined sidebar
        # if hasattr(self.main_window, 'combined_sidebar'):
        #     return (self.preview_visible and 
        #             self.main_window.combined_sidebar.is_preview_visible() and
        #             self.main_window.combined_sidebar.isVisible())
        
        # # Fallback to internal flag
        # print(f"     preview_widget.is_visible() returning {self.preview_visible} for fallback")
        # return self.preview_visible
