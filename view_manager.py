#!/usr/bin/env python3
"""
View Manager for Image Browser
Handles browse view and thumbnail view modes, view switching, and display state
"""

import os
import stat
from datetime import datetime
from typing import Optional
from PySide6.QtCore import Qt, QTimer, QSize
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QMessageBox, QApplication, 
    QTextEdit, QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView
)
from PySide6.QtGui import QPixmap, QPainter, QColor, QPen, QBrush, QStandardItemModel

# Local imports
from cursor_manager import CursorManager
from canvas_manager import CanvasManager
from exif_image_loader import load_image_with_exif_correction
from theme_service import get_active_theme
from utils import entry_debug_wrapper, entry_debug, normalize_path_for_display

class BrowseImageLabel(QLabel):
    """QLabel subclass that displays lock icon overlay in browse mode"""
    
    def __init__(self, main_window, parent=None):
        super().__init__(parent)
        self.main_window = main_window
        self._padlock_pixmap: Optional[QPixmap] = None
    
    def _load_padlock_pixmap(self) -> Optional[QPixmap]:
        """Load the padlock icon from assets folder"""
        if self._padlock_pixmap is not None:
            return self._padlock_pixmap
        
        # Try to load padlock image from assets folder
        padlock_path = os.path.join(os.path.dirname(__file__), "assets", "padlock.png")
        if os.path.exists(padlock_path):
            pixmap = QPixmap(padlock_path)
            if not pixmap.isNull():
                self._padlock_pixmap = pixmap
                return pixmap
        
        # Fallback: return None if image not found
        return None
    
    def paintEvent(self, event):
        """Override paintEvent to draw lock icon overlay"""
        super().paintEvent(event)
        
        # Only draw lock icon in browse mode and if locking is enabled
        if not hasattr(self.main_window, 'current_view_mode') or self.main_window.current_view_mode != 'browse':
            return
        
        if not getattr(self.main_window, 'allow_thumbnail_locking', False):
            return
        
        # Check if current image is locked
        if not hasattr(self.main_window, 'current_image_path') or not self.main_window.current_image_path:
            return
        
        if not hasattr(self.main_window, 'lock_manager') or not self.main_window.lock_manager:
            return
        
        if not self.main_window.lock_manager.is_file_locked(self.main_window.current_image_path):
            return
        
        # Draw lock icon - twice the size of thumbnail lock icon
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        # Icon size: twice the thumbnail size (thumbnail uses max(16, min(32, rect.width() // 8)))
        # For browse mode, use a fixed larger size
        icon_size = 64  # Twice the max thumbnail size of 32
        margin = 8
        
        # Position in upper-right corner
        padlock_x = self.width() - icon_size - margin
        padlock_y = margin
        
        # Try to load and use the padlock image
        padlock_pixmap = self._load_padlock_pixmap()
        if padlock_pixmap and not padlock_pixmap.isNull():
            # Scale the pixmap to the desired icon size
            scaled_pixmap = padlock_pixmap.scaled(
                icon_size, icon_size,
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation
            )
            # Draw the scaled padlock image
            painter.drawPixmap(int(padlock_x), int(padlock_y), scaled_pixmap)
            painter.end()
            return
        
        # Fallback: Draw a simple padlock icon using QPainter if image not found
        padlock_color = QColor(255, 215, 0)  # Gold color
        painter.setPen(QPen(padlock_color, 4))  # Thicker pen for larger icon
        painter.setBrush(QBrush(padlock_color))
        
        # Draw padlock body (rounded rectangle)
        body_width = icon_size * 0.6
        body_height = icon_size * 0.7
        body_x = padlock_x + (icon_size - body_width) / 2
        body_y = padlock_y + icon_size * 0.2
        
        # Draw rounded rectangle for padlock body
        painter.drawRoundedRect(
            int(body_x), int(body_y), 
            int(body_width), int(body_height),
            4, 4  # Larger radius for larger icon
        )
        
        # Draw padlock shackle (arch on top)
        shackle_width = icon_size * 0.5
        shackle_height = icon_size * 0.3
        shackle_x = padlock_x + (icon_size - shackle_width) / 2
        shackle_y = padlock_y + icon_size * 0.1
        
        # Draw arch (semi-circle on top)
        painter.setPen(QPen(padlock_color, 4))
        painter.setBrush(QBrush())
        # Draw arc for shackle
        painter.drawArc(
            int(shackle_x), int(shackle_y),
            int(shackle_width), int(shackle_height * 2),
            0, 180 * 16  # 180 degrees
        )
        
        painter.end()


class ViewManager:
    """Manages browse view and thumbnail view modes, view switching, and display state"""

    def __init__(self, main_window):
        self.main_window = main_window
        if hasattr(main_window, 'event_bus') and main_window.event_bus:
            from event_bus import DISPLAYED_IMAGES_CHANGED
            main_window.event_bus.subscribe(DISPLAYED_IMAGES_CHANGED, self._on_displayed_images_changed)
        # watch(self.main_window.displayed_images)

    def _on_displayed_images_changed(self, images):
        """Handle DISPLAYED_IMAGES_CHANGED - update list view when in list mode"""
        if getattr(self.main_window, 'current_view_mode', '') == 'list':
            self.update_list_view()

    def setup_browse_view(self):
        """Setup the browse view widget"""
        browse_view_widget = QWidget()
        browse_view_widget.setFocusPolicy(Qt.NoFocus)
        self.main_window._browse_view_root_widget = browse_view_widget
        browse_view_widget.setStyleSheet(get_active_theme().browse_view_shell_stylesheet())
        
        layout = QVBoxLayout(browse_view_widget)
        layout.setContentsMargins(0, 0, 0, 0)
        
        # Create a centering container for the image
        self.main_window.image_container = QWidget()
        self.main_window.image_container.setStyleSheet("background-color: transparent;")
        
        # Add centering layout to the image container
        self.main_window.image_layout = QHBoxLayout(self.main_window.image_container)
        self.main_window.image_layout.setContentsMargins(0, 0, 0, 0)
        self.main_window.image_layout.setSpacing(0)
        
        # Add stretch to center the image horizontally
        self.main_window.image_layout.addStretch()
        
        # Stretch so image_container fills browse_view_widget vertically during resize
        layout.addWidget(self.main_window.image_container, 1)
        
        self.main_window.image_label = BrowseImageLabel(self.main_window, self.main_window.image_container)
        self.main_window.image_label.setAlignment(Qt.AlignCenter)
        self.main_window.image_label.setMinimumSize(100, 100)
        self.main_window.image_label.setScaledContents(False)
        self.main_window.image_label.setFocusPolicy(Qt.NoFocus)
        self.main_window.image_label.setAttribute(Qt.WA_TransparentForMouseEvents, False)
        self.main_window.image_label.setStyleSheet("background-color: transparent;")
        
        # Add image label to the centering layout (vertically centered so letterboxing matches during resize)
        self.main_window.image_layout.addWidget(self.main_window.image_label, 0, Qt.AlignVCenter)
        
        self.main_window.slideshow_next_label = QLabel(self.main_window.image_container)
        self.main_window.slideshow_next_label.setAlignment(Qt.AlignCenter)
        self.main_window.slideshow_next_label.setMinimumSize(100, 100)
        self.main_window.slideshow_next_label.setScaledContents(False)
        self.main_window.slideshow_next_label.setFocusPolicy(Qt.NoFocus)
        self.main_window.slideshow_next_label.setStyleSheet("background-color: transparent;")
        self.main_window.slideshow_next_label.hide()
        
        # Add slideshow label to the centering layout
        self.main_window.image_layout.addWidget(self.main_window.slideshow_next_label, 0, Qt.AlignVCenter)
        
        # Add stretch to complete the centering
        self.main_window.image_layout.addStretch()
        
        self.main_window.filename_label = QTextEdit(browse_view_widget)
        self.main_window.filename_label.setReadOnly(True)
        self.main_window.filename_label.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.main_window.filename_label.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.main_window.filename_label.setFocusPolicy(Qt.NoFocus)  # Don't receive keyboard events
        # Set minimum size to ensure widget is visible
        self.main_window.filename_label.setMinimumSize(200, 50)
        _theme = get_active_theme()
        self.main_window.filename_label.setStyleSheet(_theme.browse_filename_textedit_stylesheet())
        self.main_window.filename_label.hide()
        # Don't set WA_TransparentForMouseEvents - we need mouse events for scrolling
        # Set maximum height to enable scrolling without visible scrollbars
        self.main_window.filename_label.setMaximumHeight(500)
        # Enable mouse wheel scrolling
        self.main_window.filename_label.setAcceptRichText(True)
        # Ensure QTextEdit document is properly initialized
        self.main_window.filename_label.document().setDefaultStyleSheet(_theme.browse_filename_document_stylesheet())

        # Number overlay labels (top-right) for imagegen-#### codes: shadow + foreground
        self.main_window.number_overlay_shadow_label = QLabel(browse_view_widget)
        self.main_window.number_overlay_shadow_label.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.main_window.number_overlay_shadow_label.setStyleSheet("background-color: transparent; color: black;")
        self.main_window.number_overlay_shadow_label.hide()

        self.main_window.number_overlay_label = QLabel(browse_view_widget)
        self.main_window.number_overlay_label.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.main_window.number_overlay_label.setStyleSheet("background-color: transparent; color: white;")
        self.main_window.number_overlay_label.hide()

        self.main_window.stacked_widget.addWidget(browse_view_widget)

    def refresh_browse_theme_styles(self):
        """Re-apply browse view shell and filename overlay styles when the app theme changes."""
        theme = get_active_theme()
        w = getattr(self.main_window, "_browse_view_root_widget", None)
        if w:
            w.setStyleSheet(theme.browse_view_shell_stylesheet())
        if hasattr(self.main_window, "filename_label") and self.main_window.filename_label:
            self.main_window.filename_label.setStyleSheet(theme.browse_filename_textedit_stylesheet())
            self.main_window.filename_label.document().setDefaultStyleSheet(theme.browse_filename_document_stylesheet())

    def setup_thumbnail_view(self):
        """Setup the thumbnail view widget"""
        thumbnail_widget = QWidget()
        thumbnail_widget.setFocusPolicy(Qt.NoFocus)  # Don't steal focus from tree
        
        layout = QVBoxLayout(thumbnail_widget)
        layout.setContentsMargins(0, 0, 0, 0)
        
        # Create canvas manager instead of thumbnail container
        self.main_window.thumbnail_container = CanvasManager(self.main_window, thumbnail_widget)
        
        # Set initial filename overlay visibility from config
        self.main_window.thumbnail_container.set_filename_overlay_visible(self.main_window.thumbnail_filename_visible)
        # ========================================================================
        # CRITICAL: Set NoFocus to prevent thumbnail_container from being in tab order
        # ========================================================================
        # DO NOT CHANGE THIS! The thumbnail_container must have NoFocus policy
        # to prevent it from being in the tab order. Only tree_container and
        # main_content_widget should be in the tab order.
        # ========================================================================
        self.main_window.thumbnail_container.setFocusPolicy(Qt.NoFocus)
        
        # Import spacing constants from CanvasManager
        self.main_window.HORIZONTAL_SPACING = self.main_window.thumbnail_container.HORIZONTAL_SPACING
        self.main_window.VERTICAL_SPACING = self.main_window.thumbnail_container.VERTICAL_SPACING
        
        # Get the scroll area from the canvas manager
        self.main_window.scroll_area = self.main_window.thumbnail_container.scroll_area
        
        # Connect scroll signals to handle scroll-aware thumbnail loading
        self.main_window.connect_scroll_signals()
        
        layout.addWidget(self.main_window.thumbnail_container)
        self.main_window.stacked_widget.addWidget(thumbnail_widget)

    def setup_list_view(self):
        """Setup the list view widget with canvas-based display"""
        list_view_widget = QWidget()
        list_view_widget.setFocusPolicy(Qt.NoFocus)
        
        layout = QVBoxLayout(list_view_widget)
        layout.setContentsMargins(0, 0, 0, 0)
        
        # Create list canvas manager instead of table widget
        from list_canvas_manager import ListCanvasManager
        self.main_window.list_view_container = ListCanvasManager(self.main_window, list_view_widget)
        
        # Set focus policy
        self.main_window.list_view_container.setFocusPolicy(Qt.NoFocus)
        
        # Get the scroll area from the list canvas manager
        self.main_window.list_view_scroll_area = self.main_window.list_view_container.scroll_area
        
        layout.addWidget(self.main_window.list_view_container)
        self.main_window.stacked_widget.addWidget(list_view_widget)
    
    def _on_list_item_clicked(self, row: int, column: int):
        """Handle single click on list item - no longer used with canvas view"""
        # Clicks are handled by the canvas itself now
        pass
    
    def _on_list_item_double_clicked(self, item: QTableWidgetItem):
        """Handle double-click on list item - no longer used with canvas view"""
        # Double-clicks are handled by the canvas itself now
        pass
    
    def _open_browse_from_list(self, row: int):
        """Open browse view for the image at the given row"""
        if not hasattr(self.main_window, 'displayed_images') or not self.main_window.displayed_images:
            return
        
        if row < 0 or row >= len(self.main_window.displayed_images):
            return
        
        image_path = self.main_window.displayed_images[row]
        
        # Find the index in displayed_images
        try:
            index = self.main_window.displayed_images.index(image_path)
        except ValueError:
            index = row
        
        # Store that we're coming from list view
        self.main_window._return_to_list_view = True
        
        # Open browse view
        self.open_browse_view(index)
    
    def _format_permissions(self, file_path: str, file_stat=None) -> str:
        """Format file permissions in rwxrwxrwx format"""
        try:
            if file_stat is None:
                file_stat = os.stat(file_path)
            mode = file_stat.st_mode
            permissions = stat.filemode(mode)
            # Convert from -rwxrwxrwx format to rwxrwxrwx format
            if permissions.startswith('-'):
                return permissions[1:]
            return permissions
        except Exception:
            return "----------"
    
    def _format_file_size(self, file_path: str, file_stat=None, metadata=None) -> str:
        """Format file size in human-readable format, rounded to nearest KB with no decimal places"""
        try:
            # Use cached metadata if available (fastest - no file system call)
            if metadata and hasattr(metadata, 'file_size') and metadata.file_size:
                size_bytes = metadata.file_size
            elif file_stat:
                size_bytes = file_stat.st_size
            else:
                size_bytes = os.path.getsize(file_path)
            # Round to nearest KB (no decimal places)
            size_kb = round(size_bytes / 1024.0)
            return f"{size_kb} KB"
        except Exception:
            return "0 KB"
    
    def _format_date(self, file_path: str, file_stat=None, metadata=None) -> str:
        """Format file modification date"""
        try:
            # Use cached metadata if available (fastest - no file system call)
            if metadata and hasattr(metadata, 'modified_time') and metadata.modified_time:
                mtime = metadata.modified_time
            elif file_stat:
                mtime = file_stat.st_mtime
            else:
                mtime = os.path.getmtime(file_path)
            dt = datetime.fromtimestamp(mtime)
            return dt.strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            return "0000-00-00 00:00:00"
    
    def _format_dimensions(self, file_path: str, metadata=None) -> str:
        """Format image dimensions - optimized to use cache first, skip slow loading for list view"""
        try:
            # Use cached metadata if available (fastest - no file system call)
            if metadata and hasattr(metadata, 'width') and hasattr(metadata, 'height'):
                if metadata.width > 0 and metadata.height > 0:
                    return f"{metadata.width}x{metadata.height}"
            
            # Try to get dimensions from metadata cache (if not passed in)
            if metadata is None and hasattr(self.main_window, 'cache_manager') and self.main_window.cache_manager:
                metadata = self.main_window.cache_manager.get_metadata_sync(file_path)
                if metadata and metadata.width > 0 and metadata.height > 0:
                    return f"{metadata.width}x{metadata.height}"
            
            # For list view, try fast metadata extraction but skip slow QPixmap loading
            # This avoids loading full images just for dimensions in list view
            try:
                from exif_image_loader import get_image_dimensions_fast_metadata
                dimensions = get_image_dimensions_fast_metadata(file_path)
                if dimensions and len(dimensions) == 2:
                    width, height = dimensions
                    if width > 0 and height > 0:
                        return f"{width}x{height}"
            except (ImportError, Exception):
                pass
            
            # If cache and fast metadata both fail, return 0x0 rather than loading full image
            # This keeps list view loading fast - dimensions can be loaded later if needed
            return "0x0"
        except Exception:
            return "0x0"
    
    def _on_list_header_clicked(self, column: int):
        """Handle column header click for sorting - no longer used with canvas view"""
        # Header clicks are handled by the canvas itself now
        pass
    
    def _update_list_header_sort_indicators(self):
        """Update column header labels to show sort indicators - no longer used with canvas view"""
        # Headers are drawn by the canvas itself now
        pass
    
    def update_list_view(self):
        """Update the list view with current displayed images"""
        if not hasattr(self.main_window, 'list_view_container') or not self.main_window.list_view_container:
            return
        
        if not hasattr(self.main_window, 'displayed_images') or not self.main_window.displayed_images:
            self.main_window.list_view_container.set_rows([], [])
            return
        
        displayed_images = self.main_window.displayed_images
        num_images = len(displayed_images)
        
        # Check if all files are from the same directory
        # If files are from different directories, show full path in name column
        show_full_path = False
        if displayed_images:
            try:
                # Get directory of first file
                first_dir = os.path.dirname(os.path.abspath(displayed_images[0]))
                # Check if all other files are from the same directory
                for image_path in displayed_images[1:]:
                    try:
                        current_dir = os.path.dirname(os.path.abspath(image_path))
                        if current_dir != first_dir:
                            show_full_path = True
                            break
                    except Exception:
                        # If we can't determine directory, show full path to be safe
                        show_full_path = True
                        break
            except Exception:
                # If we can't determine first directory, show full path to be safe
                show_full_path = True
        
        # OPTIMIZATION: Pre-build path-to-metadata lookup for large lists
        # This avoids O(n*m) iteration through cache for each file
        metadata_lookup = {}
        use_large_list_optimization = num_images > 1000
        if use_large_list_optimization and hasattr(self.main_window, 'cache_manager') and self.main_window.cache_manager:
            cache_manager = self.main_window.cache_manager
            if len(cache_manager.metadata_cache) > 0:
                # Build reverse lookup: path -> metadata (one-time O(m) operation)
                for key, cached_metadata in cache_manager.metadata_cache.items():
                    # Extract path from cache key (cache keys contain the path)
                    # Cache keys are typically formatted as "path|mtime|extra"
                    if '|' in key:
                        path_part = key.split('|')[0]
                    else:
                        path_part = key
                    # Normalize path for lookup
                    try:
                        normalized_path = os.path.abspath(path_part)
                        metadata_lookup[normalized_path] = cached_metadata
                    except Exception:
                        pass
        
        # PHASE 1: Gather all data to memory first (no widget operations)
        # This separates data gathering from widget population for better performance
        row_data = []  # List of tuples: (perms_text, date_text, size_text, dims_text, name_text)
        
        for row, image_path in enumerate(displayed_images):
            # Process events periodically for responsiveness
            if row % 100 == 0:
                QApplication.processEvents()
            
            # MAJOR OPTIMIZATION: Try to get metadata from cache first
            # If cached, we can get size, date, and dimensions WITHOUT any file system calls!
            metadata = None
            file_stat = None
            
            # Fast path: Try to get metadata from cache
            # For large lists, use pre-built lookup dictionary (O(1) instead of O(m))
            if use_large_list_optimization and metadata_lookup:
                # Use pre-built lookup - O(1) operation
                try:
                    abs_path = os.path.abspath(image_path)
                    metadata = metadata_lookup.get(abs_path)
                except Exception:
                    metadata = None
            elif hasattr(self.main_window, 'cache_manager') and self.main_window.cache_manager:
                # For smaller lists, use normal cache key lookup
                cache_manager = self.main_window.cache_manager
                if len(cache_manager.metadata_cache) > 0:
                    try:
                        cache_key = cache_manager.get_cache_key(image_path)
                        if cache_key in cache_manager.metadata_cache:
                            metadata = cache_manager.metadata_cache[cache_key]
                    except Exception:
                        pass
            
            # Always get file_stat for permissions (even for large lists)
            # Permissions aren't in metadata cache, so we need os.stat()
            # But we can skip it if we already have it from metadata lookup
            if file_stat is None:
                try:
                    file_stat = os.stat(image_path)
                except Exception:
                    file_stat = None
            
            # Gather all text data for this row
            # Always format permissions - file_stat should be available now
            perms_text = self._format_permissions(image_path, file_stat) if file_stat else "----------"
            date_text = self._format_date(image_path, file_stat, metadata)
            size_text = self._format_file_size(image_path, file_stat, metadata)
            dims_text = self._format_dimensions(image_path, metadata)
            # Show full path if files are from different directories, otherwise just filename
            if show_full_path:
                # Use normalize_path_for_display to replace home directory with ~
                name_text = normalize_path_for_display(image_path)
            else:
                name_text = os.path.basename(image_path)
            
            # Store row data (no widget operations yet)
            row_data.append((perms_text, date_text, size_text, dims_text, name_text))
        
        # PHASE 2: Populate canvas all at once (fast batch operation)
        # Now that all data is gathered, populate the canvas efficiently
        # Set rows on canvas (this triggers painting)
        self.main_window.list_view_container.set_rows(displayed_images, row_data)
        
        # Highlight current image if available
        if hasattr(self.main_window, 'current_image_path') and self.main_window.current_image_path:
            try:
                current_index = displayed_images.index(self.main_window.current_image_path)
                self.main_window.list_view_container.set_highlighted_index(current_index)
                self.main_window.list_view_container.scroll_to_highlighted(current_index)
            except ValueError:
                pass
        
        # Trigger lazy loading of visible thumbnails after a short delay
        # Also ensure cache manager signals are connected
        if hasattr(self.main_window.list_view_container, 'connect_cache_manager_signals'):
            self.main_window.list_view_container.connect_cache_manager_signals()
        QTimer.singleShot(200, lambda: self.main_window.list_view_container.canvas._load_visible_thumbnails())
    
    def _on_list_scroll_changed(self):
        """Handle scroll events to load thumbnails for newly visible rows"""
        if not hasattr(self.main_window, 'list_view_table') or not self.main_window.list_view_table:
            return
        
        if getattr(self.main_window, 'current_view_mode', None) != 'list':
            return
        
        # Debounce scroll events
        if hasattr(self.main_window, '_list_view_thumbnail_timer'):
            self.main_window._list_view_thumbnail_timer.stop()
            self.main_window._list_view_thumbnail_timer.start(150)  # 150ms debounce
    
    def _load_visible_thumbnails(self):
        """Trigger thumbnail loading for currently visible rows using existing thumbnail loading system"""
        if not hasattr(self.main_window, 'list_view_table') or not self.main_window.list_view_table:
            return
        
        if getattr(self.main_window, 'current_view_mode', None) != 'list':
            return
        
        if not hasattr(self.main_window, 'displayed_images') or not self.main_window.displayed_images:
            return
        
        # Get visible row range
        viewport = self.main_window.list_view_table.viewport()
        visible_rect = viewport.visibleRegion().boundingRect() if hasattr(viewport, 'visibleRegion') else viewport.rect()
        
        # Get first and last visible rows
        first_row = self.main_window.list_view_table.rowAt(visible_rect.top())
        last_row = self.main_window.list_view_table.rowAt(visible_rect.bottom())
        
        if first_row < 0:
            first_row = 0
        if last_row < 0:
            last_row = self.main_window.list_view_table.rowCount() - 1
        
        # Expand range slightly to preload nearby rows
        preload_margin = 20
        first_row = max(0, first_row - preload_margin)
        last_row = min(self.main_window.list_view_table.rowCount() - 1, last_row + preload_margin)
        
        # Get image paths for visible rows
        visible_paths = []
        for row in range(first_row, last_row + 1):
            item = self.main_window.list_view_table.item(row, 0)
            if item:
                image_path = item.data(Qt.UserRole)
                if image_path:
                    visible_paths.append(image_path)
        
        # Use existing thumbnail loading system - request thumbnails at current thumbnail size
        # The system will use cached thumbnails and resize as needed
        if visible_paths and hasattr(self.main_window, 'cache_manager') and self.main_window.cache_manager:
            # Request thumbnails at the current thumbnail size (will be resized to 64x64 in signal handler)
            current_thumb_size = getattr(self.main_window, 'current_thumbnail_size', 200)
            for image_path in visible_paths:
                # Use the existing async loading system - it will use cached thumbnails
                self.main_window.cache_manager.get_thumbnail_async(image_path, current_thumb_size, priority=1)
    
    def _on_list_thumbnail_loaded(self, image_path: str, pixmap: QPixmap, size: int):
        """Handle thumbnail loaded signal - update list view table item"""
        if not hasattr(self.main_window, 'list_view_table') or not self.main_window.list_view_table:
            return
        
        if getattr(self.main_window, 'current_view_mode', None) != 'list':
            return
        
        if not pixmap or pixmap.isNull():
            return
        
        # Find the row for this image path
        if not hasattr(self.main_window, 'displayed_images') or not self.main_window.displayed_images:
            return
        
        try:
            row = self.main_window.displayed_images.index(image_path)
        except ValueError:
            return  # Image not in current displayed list
        
        # Update the thumbnail item
        item = self.main_window.list_view_table.item(row, 0)
        if item:
            # Resize thumbnail to 64x64 for list view (regardless of original size)
            thumbnail_size = 64
            if pixmap.width() != thumbnail_size or pixmap.height() != thumbnail_size:
                scaled_pixmap = pixmap.scaled(
                    thumbnail_size, thumbnail_size,
                    Qt.KeepAspectRatio,
                    Qt.SmoothTransformation
                )
            else:
                scaled_pixmap = pixmap
            
            item.setData(Qt.DecorationRole, scaled_pixmap)
    
    def _page_down_list_view(self):
        """Page down in list view - scroll down by one viewport height"""
        if not hasattr(self.main_window, 'list_view_table') or not self.main_window.list_view_table:
            return
        
        table = self.main_window.list_view_table
        if table.rowCount() == 0:
            return
        
        # Get current selected row
        selected_rows = table.selectedIndexes()
        current_row = selected_rows[0].row() if selected_rows else 0
        
        # Use QTableWidget's built-in page down behavior by scrolling the viewport
        # Get the visible rect to determine how many rows are visible
        viewport = table.viewport()
        visible_rect = viewport.visibleRegion().boundingRect() if hasattr(viewport, 'visibleRegion') else viewport.rect()
        
        # Get first and last visible rows
        first_visible = table.rowAt(visible_rect.top())
        last_visible = table.rowAt(visible_rect.bottom())
        
        if first_visible < 0:
            first_visible = 0
        if last_visible < 0:
            last_visible = table.rowCount() - 1
        
        # Calculate rows per page (number of visible rows)
        rows_per_page = max(1, last_visible - first_visible + 1)
        
        # Calculate new row (move down by one page from current selection)
        new_row = min(table.rowCount() - 1, current_row + rows_per_page)
        
        # Select and scroll to new row
        table.selectRow(new_row)
        table.scrollToItem(
            table.item(new_row, 0),
            QAbstractItemView.EnsureVisible
        )
        
        # Update current image path if needed
        if hasattr(self.main_window, 'displayed_images') and self.main_window.displayed_images:
            if 0 <= new_row < len(self.main_window.displayed_images):
                image_path = self.main_window.displayed_images[new_row]
                if hasattr(self.main_window, '_set_current_image_path_with_sync'):
                    self.main_window._set_current_image_path_with_sync(image_path)
                else:
                    self.main_window.current_image_path = image_path
    
    def _sync_list_selection_after_key_navigation(self):
        """Sync list view selection after keyboard navigation (arrow keys)"""
        if not hasattr(self.main_window, 'list_view_table') or not self.main_window.list_view_table:
            return
        
        if getattr(self.main_window, 'current_view_mode', None) != 'list':
            return
        
        # Get current row from the table
        current_row = self.main_window.list_view_table.currentRow()
        if current_row >= 0:
            self._sync_list_selection_to_current_image(current_row)
    
    def _sync_list_selection_to_current_image_from_path(self):
        """Sync list view selection to current image path (for left/right navigation)"""
        if not hasattr(self.main_window, 'list_view_table') or not self.main_window.list_view_table:
            return
        
        if getattr(self.main_window, 'current_view_mode', None) != 'list':
            return
        
        # Get current image path from main window
        if not hasattr(self.main_window, 'current_image_path') or not self.main_window.current_image_path:
            return
        
        # Find the row index of the current image
        if not hasattr(self.main_window, 'displayed_images') or not self.main_window.displayed_images:
            return
        
        try:
            current_image_path = self.main_window.current_image_path
            row_index = self.main_window.displayed_images.index(current_image_path)
            
            # Select the row and scroll to it
            if 0 <= row_index < self.main_window.list_view_table.rowCount():
                self.main_window.list_view_table.selectRow(row_index)
                self.main_window.list_view_table.scrollToItem(
                    self.main_window.list_view_table.item(row_index, 0),
                    QAbstractItemView.EnsureVisible
                )
                # Sync selection to update metadata, tree, and preview
                self._sync_list_selection_to_current_image(row_index)
        except (ValueError, AttributeError):
            # Image not found in displayed_images - ignore
            pass
    
    def _sync_list_selection_to_current_image(self, row: int):
        """Sync list view selection to current image path"""
        if not hasattr(self.main_window, 'displayed_images') or not self.main_window.displayed_images:
            return
        
        if 0 <= row < len(self.main_window.displayed_images):
            image_path = self.main_window.displayed_images[row]
            # Set current image by path - this will sync metadata, tree, and preview
            if hasattr(self.main_window, 'set_current_image_by_path'):
                self.main_window.set_current_image_by_path(image_path)
                # Update Information sidebar, preview, and tree (same as thumbnail view)
                if hasattr(self.main_window, 'update_filename_for_new_image'):
                    self.main_window.update_filename_for_new_image()
                # Update preview widget if visible
                if hasattr(self.main_window, 'update_preview_if_visible'):
                    self.main_window.update_preview_if_visible()
                # Update tree highlighting
                if (hasattr(self.main_window, 'file_tree_handler') and 
                    self.main_window.file_tree_handler.is_tree_initialized()):
                    self.main_window.file_tree_handler.highlight_current_file()
    
    def _page_up_list_view(self):
        """Page up in list view - scroll up by one viewport height"""
        if not hasattr(self.main_window, 'list_view_table') or not self.main_window.list_view_table:
            return
        
        table = self.main_window.list_view_table
        if table.rowCount() == 0:
            return
        
        # Get current selected row
        selected_rows = table.selectedIndexes()
        current_row = selected_rows[0].row() if selected_rows else 0
        
        # Use QTableWidget's built-in page up behavior by scrolling the viewport
        # Get the visible rect to determine how many rows are visible
        viewport = table.viewport()
        visible_rect = viewport.visibleRegion().boundingRect() if hasattr(viewport, 'visibleRegion') else viewport.rect()
        
        # Get first and last visible rows
        first_visible = table.rowAt(visible_rect.top())
        last_visible = table.rowAt(visible_rect.bottom())
        
        if first_visible < 0:
            first_visible = 0
        if last_visible < 0:
            last_visible = table.rowCount() - 1
        
        # Calculate rows per page (number of visible rows)
        rows_per_page = max(1, last_visible - first_visible + 1)
        
        # Calculate new row (move up by one page from current selection)
        new_row = max(0, current_row - rows_per_page)
        
        # Select and scroll to new row
        table.selectRow(new_row)
        table.scrollToItem(
            table.item(new_row, 0),
            QAbstractItemView.EnsureVisible
        )
        
        # Update current image path if needed
        if hasattr(self.main_window, 'displayed_images') and self.main_window.displayed_images:
            if 0 <= new_row < len(self.main_window.displayed_images):
                image_path = self.main_window.displayed_images[new_row]
                if hasattr(self.main_window, '_set_current_image_path_with_sync'):
                    self.main_window._set_current_image_path_with_sync(image_path)
                else:
                    self.main_window.current_image_path = image_path

    def open_browse_view(self, index: int):
        # print(f"view_manager.py: ***** open_browse_view: index is {index}")
        """Open image in browse view mode"""
        # Get image path from displayed_images or thumbnail widgets
        if self.main_window.displayed_images and index < len(self.main_window.displayed_images):
            image_path = self.main_window.displayed_images[index]
        else:
            return
        
        # CRITICAL: Check if we should return to list view
        # The flag might be set by _open_browse_from_list or open_current_browse_view
        # But we also need to check if list_view_table exists and is visible, as current_view_mode
        # might have been reset to thumbnail by the time we get here
        return_to_list_before = getattr(self.main_window, '_return_to_list_view', False)
        
        if not return_to_list_before:
            # Check if list view table exists and is the current widget in stacked widget
            if (hasattr(self.main_window, 'list_view_table') and self.main_window.list_view_table and
                hasattr(self.main_window, 'stacked_widget') and self.main_window.stacked_widget):
                current_widget_index = self.main_window.stacked_widget.currentIndex()
                current_mode = getattr(self.main_window, 'current_view_mode', None)
                
                if current_widget_index == 2:  # List view is index 2
                    self.main_window._return_to_list_view = True
                else:
                    if current_mode == 'list':
                        self.main_window._return_to_list_view = True
        
        # Set current_image_path first - this is the source of truth
        # Use sync method to ensure proper synchronization with FileDataModel
        if hasattr(self.main_window, '_set_current_image_path_with_sync'):
            self.main_window._set_current_image_path_with_sync(image_path)
        else:
            self.main_window.current_image_path = image_path
        
        # ALWAYS derive both current_index and highlight_index from current_image_path by finding it in displayed_images
        # Never trust index variables - file path is the final truth
        try:
            if self.main_window.displayed_images:
                # Find the actual index of this file path in displayed_images
                actual_index = self.main_window.displayed_images.index(image_path)
                self.main_window.current_index = actual_index
                self.main_window.highlight_index = actual_index
            else:
                # Fallback only if displayed_images is empty
                self.main_window.current_index = index
                self.main_window.highlight_index = index
        except (ValueError, AttributeError):
            # If path not found, fallback to provided index
            self.main_window.current_index = index
            self.main_window.highlight_index = index
        
        # Update canvas highlighting - but don't call highlight_image() which might trigger navigation
        # Just update the canvas directly to avoid side effects
        if self.main_window.thumbnail_container:
            self.main_window.thumbnail_container.set_highlighted_index(self.main_window.highlight_index)
        
        # Update windowing context if we're in windowing mode (limit is specified)
        # Only call windowing if the image is not already visible in the current window
        if (hasattr(self.main_window, 'displayed_images') and self.main_window.displayed_images and 
            image_path not in self.main_window.displayed_images):
            self.main_window.update_windowing_if_needed(image_path)
        else:
            pass
        
        if self.main_window.current_view_mode == 'browse':
            # Ensure sidebar is hidden visually - NEVER show in fullscreen
            # Don't change the saved state, just hide it visually
            if hasattr(self.main_window, 'combined_sidebar'):
                self.main_window.combined_sidebar.hide()
            # Ensure image container is properly sized for current screen
            if hasattr(self.main_window, 'image_container'):
                available_size = self.main_window.get_effective_display_size()
                self.main_window.image_container.resize(available_size)
            self.main_window.show_image(self.main_window.current_image_path, self.main_window.current_index)
            self.main_window.start_background_thumbnail_loading_if_needed() # DGN Trying preloading thunbs in background

        else:
            # Reset fullscreen input ready flag initially
            self.main_window.browse_view_input_ready = False
            
            self.main_window.stacked_widget.setCurrentIndex(1)
            # Set browse mode after setting up the view
            self.main_window.current_view_mode = 'browse'
            if hasattr(self.main_window, '_emit_view_mode_changed'):
                self.main_window._emit_view_mode_changed()
            self.main_window.browse_view_action.setEnabled(False)
            
            # Update browse view widget background with current theme shell color
            if hasattr(self.main_window, 'stacked_widget') and self.main_window.stacked_widget.count() > 1:
                browse_view_widget = self.main_window.stacked_widget.widget(1)
                if browse_view_widget:
                    browse_view_widget.setStyleSheet(get_active_theme().browse_view_shell_stylesheet())
            
            # Hide left sidebar visually for clean browse view - NEVER show in browse mode
            # Don't change the saved state, just hide it visually
            if hasattr(self.main_window, 'combined_sidebar'):
                self.main_window.combined_sidebar.hide()
            
            # Manage sidebar visibility for browse mode (handles right sidebar too)
            self.main_window.manage_sidebar_visibility_for_view_mode('browse')
            
            # Ensure image container is properly sized for current screen
            if hasattr(self.main_window, 'image_container'):
                available_size = self.main_window.get_effective_display_size()
                self.main_window.image_container.resize(available_size)
            
            # Update status bar sections for browse mode
            self.main_window.update_status_bar_fit_mode()
            
            # Update filename menu text and enabled state
            self.main_window.update_filename_menu_text()
            
            # Prime and enable menu keys for view change (aboutToShow logic + shortcut registration)
            if hasattr(self.main_window, 'menu_manager'):
                self.main_window.menu_manager.prime_menu_keys_for_view_change()
            
            self._setup_cursor_manager()
            self.main_window.show_image(self.main_window.current_image_path, self.main_window.current_index)
            # show_image() already calls _update_status_bar_current_image(), but ensure it's called here too
            # to handle any edge cases where show_image might not complete
            self.main_window.update_status_bar_current_image()
            
            # Don't switch to OS fullscreen mode - just switch to fullscreen view
            # OS fullscreen is controlled by --fullscreen flag or Cmd+F toggle
            
            # Don't steal focus - let Qt handle tab navigation naturally
            self.main_window.activateWindow()
            # Add a small delay to ensure OS fullscreen mode is fully initialized
            QTimer.singleShot(50, self._ensure_fullscreen_focus)

        # No need to sync highlight_index here - we already set it correctly above based on the file path
        # The file path (current_image_path) is the source of truth, and we've already derived
        # both current_index and highlight_index from it

    def close_browse_view(self):
        """Close browse mode"""
        self.close_browse_view_action()
        
        # Check if container dimensions changed since last grid calculation
        if (hasattr(self.main_window, 'cached_container_width') and hasattr(self.main_window, 'cached_container_height') and
            self.main_window.cached_container_width is not None and self.main_window.cached_container_height is not None):
            
            current_display_size = self.main_window.get_effective_display_size()
            current_width = current_display_size.width()
            current_height = current_display_size.height()
            
            # If dimensions changed, rebuild grid - but preserve sort order
            if (current_width != self.main_window.cached_container_width or 
                current_height != self.main_window.cached_container_height):
                # CRITICAL: In specific_files_active (e.g. after cmd-K similarity search), do NOT call
                # refresh_directory - it reloads from disk and applies .prsort, overwriting the
                # similarity-ordered list. Instead, just force grid recalculation with current order.
                if getattr(self.main_window, 'specific_files_active', False):
                    if (self.main_window.displayed_images and
                        hasattr(self.main_window, 'thumbnail_container') and
                        self.main_window.thumbnail_container and
                        hasattr(self.main_window.thumbnail_container.canvas, 'reorder_thumbnails')):
                        self.main_window.thumbnail_container.canvas.reorder_thumbnails(
                            self.main_window.displayed_images, force_recalculate_grid=True)
                else:
                    self.main_window.refresh_directory()
        
        # Note: Removed duplicate _force_resize_event call here - it's already called in close_browse_view_action()

    def _delayed_browse_view_cleanup(self):
        """Batch delayed operations after closing browse view to avoid GIL deadlock.
        
        CRITICAL: This batches multiple delayed operations into a single QTimer.singleShot()
        call to prevent GIL contention when worker threads are active. Multiple QTimer.singleShot()
        calls each require dropping/reacquiring the GIL, which can deadlock when worker threads
        are waiting to acquire the GIL.
        """
        # Force update the preview if it should be visible
        if hasattr(self.main_window, 'preview_widget') and self.main_window.preview_widget:
            self.main_window.update_preview_if_visible()
        
        # Sync tree with current image when returning to thumbnail - ensures tree is expanded
        # and directory highlighted even if initial highlight_image ran before tree was ready
        if (self.main_window.current_view_mode == 'thumbnail' and
            hasattr(self.main_window, 'file_tree_handler') and self.main_window.file_tree_handler and
            self.main_window.file_tree_handler.is_tree_initialized() and
            self.main_window._is_file_tree_showing()):
            self.main_window.file_tree_handler.highlight_current_file()
        
        # Force a resize event to ensure proper layout update after fullscreen exit
        # The flag will be reset in _update_layout_after_splitter_resize when it's called
        # via the splitter resize timer, avoiding the need for another timer call here.
        self.main_window.force_resize_event()

    def close_browse_view_action(self):
        """Close browse mode"""
        if self.main_window.current_view_mode == 'browse':
            if hasattr(self.main_window, '_cancel_browse_image_history_debounce'):
                self.main_window._cancel_browse_image_history_debounce()
            # print(f"view_manager.py: close_browse_view_action: closing browse view and current image path is {self.main_window.current_image_path}")
            # Set flag to prevent status bar updates during fullscreen exit
            self.main_window.browse_view_exit_in_progress = True
            
            current_count = len(self.main_window.displayed_images) if hasattr(self.main_window, 'displayed_images') and self.main_window.displayed_images else 0
            
            # Reset fullscreen input ready flag
            self.main_window.browse_view_input_ready = False
            
            # Check if we should return to list view
            return_to_list = getattr(self.main_window, '_return_to_list_view', False)
            
            if return_to_list:
                self.main_window.stacked_widget.setCurrentIndex(2)  # List view is index 2
                self.main_window.current_view_mode = 'list'
                # Restore sidebar BEFORE emitting view mode changed (same as thumbnail branch)
                self.main_window.manage_sidebar_visibility_for_view_mode('list')
                if hasattr(self.main_window, '_emit_view_mode_changed'):
                    self.main_window._emit_view_mode_changed()
                self.main_window._return_to_list_view = False  # Reset flag
                # Update list view to highlight current image
                self.update_list_view()
            else:
                self.main_window.stacked_widget.setCurrentIndex(0)
                self.main_window.current_view_mode = 'thumbnail'
                # Restore sidebar BEFORE emitting view mode changed, so _immediate_splitter_update
                # sees correct layout (avoids refresh-then-resize double refresh when tree visible)
                self.main_window.manage_sidebar_visibility_for_view_mode('thumbnail')
                if hasattr(self.main_window, '_emit_view_mode_changed'):
                    self.main_window._emit_view_mode_changed()
                # Ensure thumbnails are populated when exiting browse mode
                # This is critical when exiting browse mode after a pipe request - placeholders
                # need to be created and pixmaps need to be loaded immediately
                if (self.main_window.displayed_images and
                    hasattr(self.main_window, 'create_immediate_placeholders')):
                    self.main_window.create_immediate_placeholders()
            self.main_window.browse_view_action.setEnabled(True)
            
            # Reset preview widget state to ensure it works properly after returning from browse mode
            if hasattr(self.main_window, 'preview_widget') and self.main_window.preview_widget:
                self.main_window.preview_widget.reset_state()
            
            # Don't apply layout during fullscreen exit - it clears all widgets!
            # The status bar layout should already be correct from the initial setup
            
            # Update filename menu text and enabled state
            self.main_window.update_filename_menu_text()
            
            # Prime and enable menu keys for view change (aboutToShow logic + shortcut registration)
            if hasattr(self.main_window, 'menu_manager'):
                self.main_window.menu_manager.prime_menu_keys_for_view_change()
            
            if self.main_window.cursor_manager:
                self.main_window.cursor_manager.disable()
                self.main_window.cursor_manager = None
                
            # Ensure cursor is visible and restored to default when exiting fullscreen
            self.main_window.setCursor(Qt.ArrowCursor)
            app = QApplication.instance()
            if app:
                app.restoreOverrideCursor()
            
            # Update status bar sections for thumbnail mode
            self.main_window.update_status_bar_sections()
            
            # Ensure highlight is properly set before making it visible
            self.main_window.highlight_image()
            
            # Update window title for active image
            self.main_window.image_display_manager.update_window_title_for_active_image()
            
            # CRITICAL: Check for file changes when exiting browse mode (in non-specific-files mode)
            # Only refresh if files actually changed to avoid unnecessary thumbnail flashing
            # Skip refresh in specific_files_active mode to avoid triggering state saves
            # that could interfere with stack navigation
            if not getattr(self.main_window, 'specific_files_active', False):
                # Use efficient refresh that only updates if files changed
                # Emit event for RefreshManager to handle
                if hasattr(self.main_window, 'event_bus') and self.main_window.event_bus:
                    from event_bus import FILES_CHANGED_ON_DISK
                    self.main_window.event_bus.emit(
                        FILES_CHANGED_ON_DISK,
                        getattr(self.main_window, 'current_directory', '') or ''
                    )
                else:
                    self.main_window._check_and_refresh_if_changed()
            
            # CRITICAL FIX: Batch all delayed operations into a single QTimer.singleShot() call
            # to prevent GIL deadlock. Multiple QTimer.singleShot() calls each require dropping
            # the GIL to connect signals, which can deadlock when worker threads are waiting
            # to acquire the GIL. Batching into a single call reduces GIL contention.
            QTimer.singleShot(100, self._delayed_browse_view_cleanup)

    def toggle_file_tree(self):
        """Toggle the visibility of the file tree and resize canvas accordingly"""
        if self.main_window.toggle_file_tree_action.isChecked():
            # Hide preview if it's visible (they can't both be shown at the same time)
            if hasattr(self.main_window, 'preview_widget') and self.main_window.preview_widget.is_visible():
                self.main_window.preview_widget.hide()
                self.main_window.preview_widget.preview_visible = False
            
            # Show file tree - initialize it if not already done
            self.main_window.ensure_tree_initialized()
            self.main_window.tree_container.show()
            
            # Restore splitter sizes using sidebar width
            # Preserve right sidebar width - only update left sidebar and main content
            total_width = self.main_window.main_splitter.width()
            current_sizes = self.main_window.main_splitter.sizes()
            right_width = current_sizes[2] if len(current_sizes) > 2 else (self.main_window.right_sidebar_width if hasattr(self.main_window, 'right_sidebar_visible') and self.main_window.right_sidebar_visible else 0)
            left_width = self.main_window.sidebar_width
            main_width = total_width - left_width - right_width
            self.main_window.main_splitter.setSizes([left_width, main_width, right_width])
            self.main_window.toggle_file_tree_action.setText('Hide File Tree')
            self.main_window.file_tree_visible = True
            # Give focus to the tree when it's shown - do this immediately and with a delay
            self.main_window.focus_tree()
            QTimer.singleShot(150, self.main_window.focus_tree)
            
            # Highlight current directory after tree is shown (delay to ensure tree is ready and thumbnails may be loaded)
            def highlight_current():
                if (hasattr(self.main_window, 'file_tree_handler') and 
                    self.main_window.file_tree_handler and 
                    self.main_window.file_tree_handler.is_tree_initialized()):
                    # CRITICAL: Don't override user-requested directory selection
                    if not self.main_window.file_tree_handler.user_requested_directory:
                        self.main_window.file_tree_handler.highlight_current_directory()
            QTimer.singleShot(200, highlight_current)
        else:
            # Hide file tree
            self.main_window.tree_container.hide()
            # Preserve right sidebar width - only update left sidebar and main content
            total_width = self.main_window.main_splitter.width()
            current_sizes = self.main_window.main_splitter.sizes()
            right_width = current_sizes[2] if len(current_sizes) > 2 else (self.main_window.right_sidebar_width if hasattr(self.main_window, 'right_sidebar_visible') and self.main_window.right_sidebar_visible else 0)
            main_width = total_width - right_width
            self.main_window.main_splitter.setSizes([0, main_width, right_width])
            self.main_window.toggle_file_tree_action.setText('Show File Tree')
            self.main_window.file_tree_visible = False
            # Give focus to the canvas when tree is hidden
            QTimer.singleShot(150, self.main_window.focus_canvas)
        
        # Save the setting
        self.main_window.config.update_setting('file_tree_visible', self.main_window.file_tree_visible)
        
        # Handle browse mode - resize image container when tree view visibility changes
        if self.main_window.current_view_mode == 'browse':
            if hasattr(self.main_window, 'image_container'):
                mw = self.main_window
                old_w = mw.cached_container_width
                old_h = mw.cached_container_height
                available_size = mw.get_effective_display_size()
                mw.image_container.resize(available_size)
                mw._handle_browse_viewport_resize_after_container_change(old_w, old_h)
        
        # Update MAX_THUMBNAIL_SIZE based on new container dimensions after tree show/hide
        QTimer.singleShot(50, self.main_window.update_max_thumbnail_size)
        
        # Force canvas to recalculate layout after toggle
        QTimer.singleShot(100, self.main_window.update_layout_after_splitter_resize)
        
        # Also force immediate update for better responsiveness
        self.main_window.main_content_widget.updateGeometry()
        self.main_window.main_content_widget.update()

    def _setup_cursor_manager(self):
        """Initialize and start cursor manager for browse mode"""
        # Clean up existing cursor manager if any
        if self.main_window.cursor_manager:
            self.main_window.cursor_manager.cleanup()
        
        # Create new cursor manager for the main window (which receives mouse events)
        # The cursor manager will handle cursor visibility on the application level
        self.main_window.cursor_manager = CursorManager(self.main_window, hide_delay_ms=2000, parent=self.main_window)
        # Start the cursor manager (starts the hide timer)
        self.main_window.cursor_manager.start()

    def open_current_browse_view(self):
        if not self.main_window.displayed_images:
            return
        
        # CRITICAL: Capture view mode BEFORE stopping slideshows, as stop_slideshow() changes current_view_mode to 'thumbnail'
        captured_view_mode = getattr(self.main_window, 'current_view_mode', None)
        captured_stacked_index = self.main_window.stacked_widget.currentIndex() if hasattr(self.main_window, 'stacked_widget') else None
        is_list_view_before_stop = (captured_view_mode == 'list') or (captured_stacked_index == 2)  # List view is index 2
        
        # Stop the slideshow if running (this may change current_view_mode to 'thumbnail')
        self.main_window.slideshow_manager.stop_slideshow()
        self.main_window.slideshow2_manager.stop_slideshow2()

        # Check if multiple files are selected - if so, view them as a group
        if len(self.main_window.selected_files) > 1:
            self.open_selected_files_fullscreen()
            return
        
        # If in list view, use highlight_index (which is already set correctly for canvas-based list view)
        # Use the CAPTURED values from before stop_slideshow() calls, as those methods change the view mode
        is_list_view = is_list_view_before_stop
        
        # For canvas-based list view, highlight_index is already correct, so we can proceed
        # The old QTableWidget-based list view check is no longer needed
        
        # Open the currently highlighted image in browse mode
        if 0 <= self.main_window.highlight_index < len(self.main_window.displayed_images):
            # Store previous view mode before opening browse
            # Use the CAPTURED values from before stop_slideshow() calls, as those methods change the view mode
            if is_list_view_before_stop:
                self.main_window._return_to_list_view = True
            self.open_browse_view(self.main_window.highlight_index)
    
    def open_selected_files_fullscreen(self):
        """Open all selected files in new level"""
        selected_files = self.main_window.selection_manager.get_selected_files()
        
        if not selected_files:
            if self.main_window.status_notification:
                self.main_window.status_notification.show_message("No files selected. Use ⌘+Shift+arrow keys or ⌘+click to select files first.")
            return
        
        if len(selected_files) == 1:
            # Find the index of the selected file
            displayed_images = self.main_window.displayed_images
            for idx, image_path in enumerate(displayed_images):
                if image_path == selected_files[0]:
                    self.open_browse_view(idx)
                    break
        else:
            # Save current state before switching to selected files view
            # This creates a new "pseudo directory" level that should be saved
            # We need to ensure the state is captured BEFORE switching to specific files mode
            if hasattr(self.main_window, 'directory_stack_history_handler'):
                # Force immediate state capture to avoid timing issues
                current_state = self.main_window.directory_stack_history_handler.capture_current_state()
                if current_state and not self.main_window.directory_stack_history_handler.is_duplicate_state(current_state):
                    self.main_window.directory_stack_history_handler.backward_stack.append(current_state)
                    self.main_window.directory_stack_history_handler.forward_stack.clear()  # Clear forward stack
            
            # Process multiple selected files as if they came from the API
            # This allows multi-selection to be used for viewing groups of images
            configuration = {'files': selected_files}
            self.main_window.refresh_from_configuration(configuration)
            self.main_window.clear_selection()

    def _ensure_fullscreen_focus(self):
        """Ensure proper focus for browse keyboard event handling"""
        if self.main_window.current_view_mode == 'browse':
            # Don't steal focus - let Qt handle tab navigation naturally
            self.main_window.raise_()
            self.main_window.browse_view_input_ready = True
