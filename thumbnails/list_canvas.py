#!/usr/bin/env python3
"""
List Canvas for Image Browser
Canvas-based list view that renders rows efficiently, similar to ThumbnailCanvas
"""

# Standard library imports
import os
import stat
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional, Set, Tuple

# Third-party imports
from PySide6.QtCore import (
    QMimeData, QMutex, QMutexLocker, QPoint, QRect, QTimer,
    Qt, QUrl, Signal
)
from PySide6.QtGui import (
    QBrush, QColor, QContextMenuEvent, QDrag, QDragEnterEvent, QDragLeaveEvent, QDragMoveEvent,
    QDropEvent, QFont, QKeyEvent, QMouseEvent, QPaintEvent, QPainter, QPen,
    QPixmap, QResizeEvent, QWheelEvent
)
from PySide6.QtWidgets import QWidget, QApplication

# Local imports
import thumbnails.thumbnail_constants as tc
from thumbnails.thumbnail_constants import (
    BASE_MARGIN, CANVAS_TOP_MARGIN, CANVAS_BOTTOM_MARGIN, CANVAS_TOTAL_TOP_MARGIN,
    inset_rect_for_stroke,
)

# List view constants
LIST_THUMBNAIL_HEIGHT = 32  # Height of thumbnail in list view
LIST_ROW_HEIGHT = LIST_THUMBNAIL_HEIGHT  # Height of each row in pixels
LIST_THUMBNAIL_WIDTH = 2 * LIST_THUMBNAIL_HEIGHT  # Width of thumbnail in list view (128x64)
LIST_COLUMN_SPACING = 12  # Spacing between columns
LIST_ROW_SPACING = 0  # No spacing - we'll draw lines instead
LIST_HEADER_HEIGHT = 32  # Height of header row
MAX_ROW_HEIGHT = 128  # Maximum row height in pixels

@dataclass
class ListRowItem:
    """Represents a single row in the list view"""
    image_path: str
    index: int
    pixmap: Optional[QPixmap] = None  # Thumbnail pixmap
    is_loading: bool = True
    rect: QRect = None
    is_highlighted: bool = False
    is_selected: bool = False
    # Column data (pre-computed for performance)
    perms_text: str = "----------"
    date_text: str = "0000-00-00 00:00:00"
    size_text: str = "0 KB"
    dims_text: str = "0x0"
    name_text: str = ""

class ListCanvas(QWidget):
    """
    Canvas-based list view that renders rows efficiently.
    Similar to ThumbnailCanvas but displays items as a list with columns.
    """
    
    # Signals to maintain compatibility with existing code
    # On macOS: cmd_pressed=Command(⌘) for multiselect, macos_ctrl_pressed=Control(⌃) for context menu
    thumbnail_clicked = Signal(int, bool, bool, bool)  # index, cmd_pressed, shift_pressed, macos_ctrl_pressed
    thumbnail_double_clicked = Signal(int)  # index
    thumbnail_hovered = Signal(int)  # index
    
    # Custom MIME types for drag and drop
    MIME_TYPE = 'application/x-imagebrowser-path'
    MULTIPLE_MIME_TYPE = 'application/x-imagebrowser-multiple-paths'

    def _delineation_pen(self) -> QPen:
        """Use disabled-text tone for list/header delineation lines."""
        line_color = QColor(tc.TEXT_DISABLED_HEX)
        if not line_color.isValid():
            line_color = tc.DEFAULT_BORDER_COLOR
        return QPen(line_color, 1)
    
    def __init__(self, main_window, parent=None):
        super().__init__(parent)
        self.main_window = main_window
        
        # List row data
        self.rows: List[ListRowItem] = []
        
        # Load row height from config (default 48)
        from config import get_config
        config = get_config()
        settings = config.load_settings()
        self.row_height = settings.get('list_view_row_height', 48)
        # Ensure row height is within valid range (28-64)
        self.row_height = max(28, min(MAX_ROW_HEIGHT, self.row_height))
        
        # Column widths - ALL FIXED except 'name' which stretches
        # These must match exactly between header and row painting
        # Thumbnail width is 2x height (based on current row height)
        thumbnail_width = 2 * self.row_height
        self.column_widths = {
            'thumbnail': thumbnail_width,
            'permissions': 70,  # Fixed width for permissions
            'date': 130,  # Fixed width for date/time
            'size': 70,  # Fixed width for size
            'dimensions': 100,  # Fixed width for dimensions
            'name': 0  # Will stretch to fill remaining space
        }
        
        # Selection and highlighting
        self.highlighted_index = -1
        self.selected_indices: Set[int] = set()
        self.multi_select_mode = False
        
        # Cache column positions to avoid recalculating on every paint
        self._cached_col_x = None
        self._cached_row_width = None
        
        # Mouse interaction
        self._drag_start_pos: Optional[QPoint] = None
        self._dragging = False
        self._hovered_index = -1
        # Timer to delay single-click handling to allow double-click detection
        self._single_click_timer = QTimer()
        self._single_click_timer.setSingleShot(True)
        self._single_click_timer.timeout.connect(self._handle_delayed_single_click)
        self._pending_click_data = None  # (index, cmd_pressed, shift_pressed, macos_ctrl_pressed)
        
        # Drag and drop
        self._show_drop_indicator = False
        self._current_insertion_index = None
        
        # Performance optimization
        self._visible_rect = QRect()
        self.needs_repaint = True
        
        # Thread safety
        self.mutex = QMutex()
        
        # Placeholder pixmap (reused for all rows) - size matches current thumbnail size
        thumbnail_width = 2 * self.row_height
        self._placeholder_pixmap = QPixmap(thumbnail_width, self.row_height)
        if self._placeholder_pixmap.isNull():
            # If pixmap creation failed, create a minimal valid pixmap
            self._placeholder_pixmap = QPixmap(max(1, thumbnail_width), max(1, self.row_height))
        # Fill with a visible gray color and draw a border so it's clearly visible
        self._placeholder_pixmap.fill(QColor(80, 80, 80))  # Medium gray so placeholder is clearly visible
        # Draw a border on the placeholder to make it more visible
        from PySide6.QtGui import QPainter as QPixmapPainter
        pixmap_painter = QPixmapPainter(self._placeholder_pixmap)
        pixmap_painter.setPen(QPen(QColor(120, 120, 120), 2))
        thumbnail_width = 2 * self.row_height
        pixmap_painter.drawRect(0, 0, thumbnail_width - 1, self.row_height - 1)
        pixmap_painter.end()
        
        # Enable drag and drop
        self.setAcceptDrops(True)
        
        # Set focus policy - allow focus for keyboard navigation but exclude from tab order
        # Use ClickFocus instead of StrongFocus to prevent Tab key navigation
        self.setFocusPolicy(Qt.ClickFocus)  # Allow focus via click but not via Tab key
        
        # Set minimum size
        self.setMinimumSize(200, 200)
        
        # Connect to cache manager signals if available
        self._connect_cache_signals()

        # Repaint when deleted placeholders change (formatted list restore)
        if hasattr(main_window, 'event_bus') and main_window.event_bus:
            from event_bus import DELETED_PLACEHOLDERS_CHANGED
            main_window.event_bus.subscribe(DELETED_PLACEHOLDERS_CHANGED, self.update)

    def _connect_cache_signals(self):
        """Connect to cache manager signals for thumbnail loading"""
        if hasattr(self.main_window, 'cache_manager') and self.main_window.cache_manager:
            try:
                import warnings
                signal = self.main_window.cache_manager.thumbnail_ready
                # Disconnect first to avoid duplicates (try/catch handles case where not connected)
                # Suppress RuntimeWarning about failed disconnect
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore", RuntimeWarning)
                    try:
                        signal.disconnect(self.on_thumbnail_loaded)
                    except (TypeError, RuntimeError):
                        # Signal not connected to this slot - this is OK, ignore error
                        pass
                signal.connect(self.on_thumbnail_loaded, Qt.QueuedConnection)
            except Exception:
                # Silently fail if connection fails
                pass
    
    def set_rows(self, image_paths: List[str], row_data: List[Tuple[str, str, str, str, str]]):
        """
        Set the rows to display in list view
        
        Args:
            image_paths: List of image file paths
            row_data: List of tuples (perms_text, date_text, size_text, dims_text, name_text) for each row
        """
        # Ensure canvas has a proper size before setting rows
        # Don't resize here - let _update_row_rectangles handle sizing
        # This prevents conflicts with setFixedSize calls
        
        with QMutexLocker(self.mutex):
            self.rows.clear()
            for i, (image_path, row_info) in enumerate(zip(image_paths, row_data)):
                perms_text, date_text, size_text, dims_text, name_text = row_info
                # Ensure permissions text is not empty
                if not perms_text or perms_text.strip() == "":
                    perms_text = "----------"
                item = ListRowItem(
                    image_path=image_path,
                    index=i,
                    is_loading=True,
                    perms_text=perms_text,
                    date_text=date_text,
                    size_text=size_text,
                    dims_text=dims_text,
                    name_text=name_text
                )
                self.rows.append(item)
        
        # Update row rectangles and canvas size
        self._update_row_rectangles()
        # Clear cached column positions since canvas size may have changed
        self._cached_col_x = None
        self._cached_row_width = None
        self.needs_repaint = True
        
        # Ensure canvas is visible and properly sized
        self.show()
        self.setVisible(True)
        
        # Force immediate update
        self.update()
        QApplication.processEvents()
        
        # Trigger lazy loading of visible thumbnails after a short delay
        # This ensures the canvas is fully rendered before loading thumbnails
        # Use longer delay to ensure everything is set up
        QTimer.singleShot(300, self._load_visible_thumbnails)
    
    def _update_row_rectangles(self):
        """Update rectangles for all rows based on current layout"""
        if not self.rows:
            # If no rows, set a minimum canvas size
            viewport_width = self.get_viewport_width()
            if viewport_width <= 0:
                viewport_width = 800
            # Use setFixedSize instead of resize for consistency
            self.setFixedSize(viewport_width, 100)  # Minimum height for empty canvas
            return
        
        viewport_width = self.get_viewport_width()
        # Ensure we have a valid width - try multiple methods
        if viewport_width <= 0:
            # Try to get from widget itself
            viewport_width = self.width()
            if viewport_width <= 0:
                # Try to get from parent scroll area
                parent = self.parent()
                while parent:
                    if hasattr(parent, 'viewport'):
                        viewport_width = parent.viewport().width()
                        if viewport_width > 0:
                            break
                    if hasattr(parent, 'scroll_area') and hasattr(parent.scroll_area, 'viewport'):
                        viewport_width = parent.scroll_area.viewport().width()
                        if viewport_width > 0:
                            break
                    parent = parent.parent()
            
            # Final fallback
            if viewport_width <= 0:
                viewport_width = 800  # Default width
        
        # Start rows at top (header is now separate widget, not part of canvas)
        # Use small top margin since header is separate
        y = 5  # Small top margin for visual spacing
        
        # Calculate minimum required width for all fixed columns
        # Use shared method to calculate column positions (without row_width since we're calculating min width)
        temp_col_x = self._calculate_column_positions()
        min_required_width = temp_col_x['name'] + 200 + BASE_MARGIN  # 200px minimum for name column
        
        # Size table to fit viewport if data fits, otherwise use minimum required width
        # This prevents horizontal scrollbar unless data won't fit
        if min_required_width <= viewport_width:
            canvas_width = viewport_width
        else:
            canvas_width = min_required_width
        
        # Calculate row width (ensure it's positive and accounts for margins)
        row_width = canvas_width - (BASE_MARGIN * 2)
        
        # Set rectangles for all rows
        for row_item in self.rows:
            row_item.rect = QRect(
                BASE_MARGIN,
                y,
                row_width,
                self.row_height
            )
            y += self.row_height  # No spacing - separator lines will be drawn
        
        # Update canvas size - ensure minimum height and proper width
        total_height = max(y + CANVAS_BOTTOM_MARGIN, 100)  # Minimum height for empty canvas
        # Set canvas size to ensure all columns fit
        self.setFixedSize(canvas_width, total_height)
        self.updateGeometry()
    
    def get_viewport_width(self) -> int:
        """Get the width of the viewport (accounting for scrollbars)"""
        # Find the scroll area parent (same approach as ThumbnailCanvas)
        scroll_area = self.parent()
        while scroll_area and not hasattr(scroll_area, 'viewport'):
            scroll_area = scroll_area.parent()
        
        if scroll_area and hasattr(scroll_area, 'viewport'):
            # Get the actual viewport width from the scroll area
            viewport_width = scroll_area.viewport().width()
            
            # Account for potential scrollbar space
            scrollbar = scroll_area.verticalScrollBar()
            if scrollbar and scrollbar.isVisible():
                viewport_width -= scrollbar.width()
            
            if viewport_width > 0:
                return viewport_width
        
        # Try alternative: look for scroll_area attribute in parent
        parent = self.parent()
        while parent:
            if hasattr(parent, 'scroll_area') and hasattr(parent.scroll_area, 'viewport'):
                viewport_width = parent.scroll_area.viewport().width()
                scrollbar = parent.scroll_area.verticalScrollBar()
                if scrollbar and scrollbar.isVisible():
                    viewport_width -= scrollbar.width()
                if viewport_width > 0:
                    return viewport_width
            parent = parent.parent()
        
        # Fallback to widget width or a reasonable default
        widget_width = self.width()
        if widget_width > 0:
            return widget_width
        
        # Default width if widget isn't sized yet
        return 1200  # Increased default to ensure columns fit
    
    def get_viewport_height(self) -> int:
        """Get the height of the viewport"""
        parent = self.parent()
        while parent:
            if hasattr(parent, 'viewport'):
                return parent.viewport().height()
            parent = parent.parent()
        return self.height()
    
    def showEvent(self, event):
        """Handle show events - ensure rows are displayed when widget becomes visible"""
        super().showEvent(event)
        if self.rows:
            # Delay update slightly to ensure viewport is sized
            QTimer.singleShot(50, lambda: (
                self._update_row_rectangles(),
                self.update()
            ))
    
    def resizeEvent(self, event):
        """Handle resize events - update row rectangles"""
        super().resizeEvent(event)
        if self.rows:
            # Clear cached column positions on resize
            self._cached_col_x = None
            self._cached_row_width = None
            self._update_row_rectangles()
            self.update()
    
    def paintEvent(self, event: QPaintEvent):
        """Paint the list rows on the canvas"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        try:
            # Paint only visible area background for performance
            self._visible_rect = event.rect()
            # If visible rect is invalid (empty), use full widget rect for initial paint
            if not self._visible_rect.isValid():
                self._visible_rect = self.rect()
            painter.fillRect(self._visible_rect, tc.DEFAULT_BACKGROUND_COLOR)
            
            with QMutexLocker(self.mutex):
                # Header is now painted by separate ListHeaderWidget - don't paint it here
                # CRITICAL PERFORMANCE FIX: Only paint visible rows
                # Painting all 12,000 rows causes terrible scrolling performance
                
                # Draw top border line before the first row
                if self.rows:
                    first_row = self.rows[0]
                    if first_row.rect and first_row.rect.isValid():
                        # Draw top border if first row is visible or if we're doing initial paint
                        if not self._visible_rect.isValid() or self._visible_rect.intersects(first_row.rect):
                            line_y = first_row.rect.top()
                            painter.setPen(self._delineation_pen())
                            painter.drawLine(first_row.rect.left(), line_y, first_row.rect.right(), line_y)
                
                painted_count = 0
                for i, row_item in enumerate(self.rows):
                    if row_item.rect and row_item.rect.isValid():
                        # Paint row if it intersects visible area OR if visible rect is empty (initial paint)
                        # Empty visible rect means we should paint all visible rows
                        if not self._visible_rect.isValid() or self._visible_rect.intersects(row_item.rect):
                            self._paint_row(painter, row_item)
                            painted_count += 1
                            
                            # Draw separator line below row (including after last row)
                            is_last_row = (i == len(self.rows) - 1)
                            if not is_last_row:
                                # Only draw separator if next row might be visible
                                next_row = self.rows[i + 1] if i + 1 < len(self.rows) else None
                                if next_row and next_row.rect and self._visible_rect.intersects(next_row.rect):
                                    line_y = row_item.rect.bottom()
                                    painter.setPen(self._delineation_pen())
                                    painter.drawLine(row_item.rect.left(), line_y, row_item.rect.right(), line_y)
                                elif row_item.rect.bottom() <= self._visible_rect.bottom():
                                    # Draw separator if it's in visible area
                                    line_y = row_item.rect.bottom()
                                    painter.setPen(self._delineation_pen())
                                    painter.drawLine(row_item.rect.left(), line_y, row_item.rect.right(), line_y)
                            else:
                                # Draw separator after last row if it's visible
                                if row_item.rect.bottom() <= self._visible_rect.bottom():
                                    line_y = row_item.rect.bottom()
                                    painter.setPen(self._delineation_pen())
                                    painter.drawLine(row_item.rect.left(), line_y, row_item.rect.right(), line_y)
            
            # Paint drop indicator if needed
            self.paintDropIndicator(painter)
        finally:
            painter.end()
    
    def _calculate_column_positions(self, row_width=None):
        """
        Calculate column x positions - shared by header and rows to ensure alignment.
        All columns are fixed width except 'name' which fills remaining space.
        Uses caching to avoid recalculating on every paint.
        
        Args:
            row_width: Optional row width. If None, uses canvas width.
        """
        # Cache column positions if row_width matches cached value
        if row_width == self._cached_row_width and self._cached_col_x:
            return self._cached_col_x
        
        col_x = {}
        x = BASE_MARGIN
        
        # Thumbnail - fixed width
        col_x['thumbnail'] = x
        x += self.column_widths['thumbnail'] + LIST_COLUMN_SPACING
        
        # Permissions - fixed width
        col_x['permissions'] = x
        x += self.column_widths['permissions'] + LIST_COLUMN_SPACING
        
        # Date - fixed width
        col_x['date'] = x
        x += self.column_widths['date'] + LIST_COLUMN_SPACING
        
        # Size - fixed width
        col_x['size'] = x
        x += self.column_widths['size'] + LIST_COLUMN_SPACING
        
        # Dimensions - fixed width
        col_x['dimensions'] = x
        x += self.column_widths['dimensions'] + LIST_COLUMN_SPACING
        
        # Name - starts here, fills remaining space
        col_x['name'] = x
        
        # Calculate name column width if row_width provided
        if row_width is not None:
            col_x['name_width'] = row_width - (x - BASE_MARGIN)
        else:
            col_x['name_width'] = 0  # Will be calculated in paint methods
        
        # Cache the result
        self._cached_col_x = col_x
        self._cached_row_width = row_width
        
        return col_x
    
    def _paint_header(self, painter: QPainter):
        """Paint the column headers"""
        header_y = CANVAS_TOP_MARGIN
        header_height = LIST_HEADER_HEIGHT
        
        # Get canvas width for calculating name column width
        canvas_width = self.width()
        if canvas_width <= 0:
            canvas_width = self.get_viewport_width()
        if canvas_width <= 0:
            canvas_width = 1200  # Fallback
        header_width = max(100, canvas_width - (BASE_MARGIN * 2))
        
        # Calculate column positions using shared method - pass width for name column calculation
        col_x = self._calculate_column_positions(row_width=header_width)
        
        # Draw header background
        header_rect = QRect(BASE_MARGIN, header_y, header_width, header_height)
        painter.fillRect(header_rect, QColor(50, 50, 50))
        
        # Draw header text - use white color
        painter.setPen(QColor(255, 255, 255))  # White text for header
        font = QFont("Arial", 13)
        font.setBold(True)
        painter.setFont(font)
        
        headers = [
            ('thumbnail', 'X'),
            ('permissions', 'Perm'),
            ('date', 'Date'),
            ('size', 'Size'),
            ('dimensions', 'Dimensions'),
            ('name', 'Name')
        ]
        
        for col_key, header_text in headers:
            x_pos = col_x[col_key]
            if col_key == 'name':
                col_width = col_x.get('name_width', header_width - (x_pos - BASE_MARGIN))
                align = Qt.AlignLeft | Qt.AlignVCenter  # Name column left-aligned
            else:
                col_width = self.column_widths[col_key]
                align = Qt.AlignCenter | Qt.AlignVCenter  # All other columns centered
            
            if col_width > 0:
                header_text_rect = QRect(x_pos, header_y, col_width, header_height)
                painter.drawText(header_text_rect, align, header_text)
                
                # Draw vertical separator line after this column (except after name column)
                if col_key != 'name':
                    line_x = x_pos + col_width
                    painter.setPen(self._delineation_pen())
                    painter.drawLine(line_x, header_y, line_x, header_y + header_height)
    
    def _paint_row(self, painter: QPainter, row_item: ListRowItem):
        """Paint a single list row"""
        if not row_item.rect or not row_item.rect.isValid():
            return
        
        rect = row_item.rect
        
        # Safety check: ensure rectangle is valid and within reasonable bounds
        if rect.width() <= 0 or rect.height() <= 0:
            return
        
        # Ensure rect has valid coordinates
        if rect.x() < 0 or rect.y() < 0:
            return
        
        # Determine if this row is highlighted or selected
        is_highlighted = row_item.index == self.highlighted_index
        is_selected = row_item.index in self.selected_indices
        
        # Check if file is locked
        is_locked = self._is_file_locked(row_item.image_path)
        
        # Calculate column positions using shared method - pass row width for name column
        # Use cached positions if available for performance
        row_width = rect.width()
        col_x = self._calculate_column_positions(row_width=row_width)
        
        # Draw background only for sortable columns (permissions through name)
        # This ensures the 'perm' cell coloring starts at the left line of that column
        if is_highlighted or is_selected:
            if self.multi_select_mode and is_selected:
                bg_color = tc.MULTISELECT_BACKGROUND_COLOR
            elif is_highlighted:
                bg_color = tc.CURRENT_IMAGE_BACKGROUND_COLOR
            else:
                bg_color = tc.MULTISELECT_BACKGROUND_COLOR
        else:
            base = tc.DEFAULT_BACKGROUND_COLOR
            if base.lightness() > 135:
                bg_color = QColor(base).darker(103)
            else:
                bg_color = QColor(base).lighter(115)
        
        # Draw background only for sortable columns
        # Start at the vertical line after thumbnail (same as header)
        # End at the right border line (rect.right())
        sortable_start_x = col_x['thumbnail'] + self.column_widths['thumbnail']
        sortable_end_x = rect.right()
        bg_rect = QRect(sortable_start_x, rect.y(), sortable_end_x - sortable_start_x, rect.height())
        
        painter.setPen(Qt.NoPen)
        painter.setBrush(bg_color)
        painter.drawRect(bg_rect)
        painter.setBrush(Qt.NoBrush)
        
        # Draw thumbnail - size matches current row height (width is 2x height)
        thumb_width = 2 * self.row_height
        thumb_height = self.row_height
        thumb_x = col_x['thumbnail']
        thumb_y = rect.y()  # Top of row (thumbnail height matches row height)
        thumb_rect = QRect(thumb_x, thumb_y, thumb_width, thumb_height)
        
        if row_item.pixmap and not row_item.pixmap.isNull():
            # Draw thumbnail pixmap - scale to fit while maintaining aspect ratio
            scaled_pixmap = row_item.pixmap.scaled(
                thumb_width, thumb_height,
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation
            )
            # Center the scaled pixmap in the rect
            px = thumb_x + (thumb_width - scaled_pixmap.width()) // 2
            py = thumb_y + (thumb_height - scaled_pixmap.height()) // 2
            painter.drawPixmap(px, py, scaled_pixmap)
        else:
            # Draw placeholder - fills entire space
            painter.drawPixmap(thumb_x, thumb_y, self._placeholder_pixmap)

        # Draw red X overlay for deleted files (formatted list placeholder)
        # Only draw if path in placeholders AND file does not exist (restore = file exists = no X)
        placeholders = getattr(self.main_window, 'deleted_file_placeholders', None)
        if placeholders and row_item.image_path in placeholders:
            if not os.path.exists(row_item.image_path):
                self._draw_deleted_overlay(painter, thumb_rect)

        # Draw text columns - ALL FIXED WIDTH except name
        painter.setPen(tc.TEXT_COLOR)
        font = QFont("Arial", 13)
        painter.setFont(font)
        font_metrics = painter.fontMetrics()
        
        # Permissions (left aligned, fixed width, centered vertically)
        perms_x = col_x['permissions']
        perms_width = self.column_widths['permissions']
        perms_rect = QRect(perms_x, rect.y(), perms_width, rect.height())
        # Draw permissions text - use fixed width, no wrapping
        perms_text = row_item.perms_text if row_item.perms_text else "----------"
        painter.drawText(perms_rect, Qt.AlignLeft | Qt.AlignVCenter, perms_text)
        
        # Date (right aligned, fixed width, centered vertically)
        # Add 8px padding-right (reduce width by 8px to create space before separator line)
        date_x = col_x['date']
        date_width = self.column_widths['date'] - 8
        date_rect = QRect(date_x, rect.y(), date_width, rect.height())
        painter.drawText(date_rect, Qt.AlignRight | Qt.AlignVCenter, row_item.date_text)
        
        # Size (right aligned, fixed width, centered vertically)
        # Add 8px padding-right (reduce width by 8px to create space before separator line)
        size_x = col_x['size']
        size_width = self.column_widths['size'] - 8
        size_rect = QRect(size_x, rect.y(), size_width, rect.height())
        painter.drawText(size_rect, Qt.AlignRight | Qt.AlignVCenter, row_item.size_text)
        
        # Dimensions (right aligned, fixed width, centered vertically)
        # Add 8px padding-right (reduce width by 8px to create space before separator line)
        dims_x = col_x['dimensions']
        dims_width = self.column_widths['dimensions'] - 8
        dims_rect = QRect(dims_x, rect.y(), dims_width, rect.height())
        painter.drawText(dims_rect, Qt.AlignRight | Qt.AlignVCenter, row_item.dims_text)
        
        # Name (left aligned, fills remaining space, centered vertically)
        name_x = col_x['name']
        name_width = col_x.get('name_width', row_width - (name_x - BASE_MARGIN))
        if name_width > 0:
            # Use elided text if name is too long
            elided_name = font_metrics.elidedText(row_item.name_text, Qt.ElideRight, name_width)
            name_rect = QRect(name_x, rect.y(), name_width, rect.height())
            painter.drawText(name_rect, Qt.AlignLeft | Qt.AlignVCenter, elided_name)
        
        # Draw vertical separator lines between columns
        painter.setPen(self._delineation_pen())
        # Left border line
        left_line_x = rect.left()
        painter.drawLine(left_line_x, rect.y(), left_line_x, rect.bottom())
        # Line after thumbnail
        thumb_line_x = col_x['thumbnail'] + self.column_widths['thumbnail']
        painter.drawLine(thumb_line_x, rect.y(), thumb_line_x, rect.bottom())
        # Line after permissions
        perms_line_x = col_x['permissions'] + self.column_widths['permissions']
        painter.drawLine(perms_line_x, rect.y(), perms_line_x, rect.bottom())
        # Line after date
        date_line_x = col_x['date'] + self.column_widths['date']
        painter.drawLine(date_line_x, rect.y(), date_line_x, rect.bottom())
        # Line after size
        size_line_x = col_x['size'] + self.column_widths['size']
        painter.drawLine(size_line_x, rect.y(), size_line_x, rect.bottom())
        # Line after dimensions
        dims_line_x = col_x['dimensions'] + self.column_widths['dimensions']
        painter.drawLine(dims_line_x, rect.y(), dims_line_x, rect.bottom())
        # Right border line
        right_line_x = rect.right()
        painter.drawLine(right_line_x, rect.y(), right_line_x, rect.bottom())
        
        # Draw border if highlighted or selected (per-border width)
        if is_highlighted or is_selected:
            if self.multi_select_mode and is_selected:
                pen_color = tc.MULTISELECT_BORDER_COLOR
                bw = int(getattr(tc, "MULTISELECT_BORDER_WIDTH_PX", 2))
            elif is_highlighted:
                pen_color = tc.CURRENT_IMAGE_BORDER_COLOR
                bw = int(getattr(tc, "CURRENT_IMAGE_BORDER_WIDTH_PX", 2))
            else:
                pen_color = tc.MULTISELECT_BORDER_COLOR
                bw = int(getattr(tc, "MULTISELECT_BORDER_WIDTH_PX", 2))
            if bw > 0:
                painter.setPen(QPen(pen_color, bw))
                painter.drawRect(inset_rect_for_stroke(rect, bw))
        
        # Draw padlock icon for locked files (skip in list view)
        # List view does not show lock symbols
        # if is_locked:
        #     self._draw_padlock_overlay(painter, thumb_rect)
    
    def _is_file_locked(self, image_path: str) -> bool:
        """Check if file is locked"""
        if not hasattr(self.main_window, 'lock_manager') or not self.main_window.lock_manager:
            return False
        return self.main_window.lock_manager.is_file_locked(image_path)

    def _draw_deleted_overlay(self, painter: QPainter, rect: QRect):
        """Draw red X corner-to-corner over thumbnail (deleted file placeholder in formatted list)"""
        painter.save()
        x_color = QColor(220, 50, 50)
        line_width = 2
        shorten_factor = 5
        x1, y1 = rect.x() + margin + shorten_factor, rect.y() + margin + shorten_factor
        x2, y2 = rect.right() - margin - shorten_factor, rect.bottom() - margin - shorten_factor
        painter.setPen(QPen(x_color, line_width))
        painter.setBrush(Qt.NoBrush)
        margin = line_width
        x1, y1 = rect.x() + margin, rect.y() + margin
        x2, y2 = rect.right() - margin, rect.bottom() - margin
        painter.drawLine(x1, y1, x2, y2)
        painter.drawLine(x2, y1, x1, y2)
        painter.restore()

    def _draw_padlock_overlay(self, painter: QPainter, rect: QRect):
        """Draw padlock icon overlay"""
        # Try to load padlock image
        padlock_path = os.path.join(os.path.dirname(__file__), "assets", "padlock.png")
        if os.path.exists(padlock_path):
            padlock_pixmap = QPixmap(padlock_path)
            if not padlock_pixmap.isNull():
                icon_size = 16
                scaled = padlock_pixmap.scaled(icon_size, icon_size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                painter.drawPixmap(rect.right() - icon_size - 2, rect.top() + 2, scaled)
                return
        
        # Fallback: draw simple padlock
        padlock_color = QColor(255, 215, 0)
        painter.setPen(QPen(padlock_color, 2))
        painter.setBrush(QBrush(padlock_color))
        icon_size = 16
        x = rect.right() - icon_size - 2
        y = rect.top() + 2
        # Draw simple padlock shape
        painter.drawRoundedRect(x, y + 4, icon_size * 0.6, icon_size * 0.7, 2, 2)
        painter.setBrush(QBrush())
        painter.drawArc(x, y, icon_size * 0.5, icon_size * 0.3, 0, 180 * 16)
    
    def _get_row_at_position(self, pos: QPoint) -> Optional[int]:
        """Get the row index at the given position"""
        for row_item in self.rows:
            if row_item.rect and row_item.rect.contains(pos):
                return row_item.index
        return None
    
    def _load_visible_thumbnails(self):
        """Load thumbnails for visible rows"""
        if not hasattr(self.main_window, 'cache_manager') or not self.main_window.cache_manager:
            return
        
        cache_manager = self.main_window.cache_manager
        
        # Get scroll area from parent
        scroll_area = None
        parent = self.parent()
        while parent:
            if hasattr(parent, 'scroll_area'):
                scroll_area = parent.scroll_area
                break
            parent = parent.parent()
        
        if not scroll_area:
            return
        
        # Get viewport dimensions
        viewport_height = scroll_area.viewport().height()
        scroll_bar = scroll_area.verticalScrollBar()
        viewport_top = scroll_bar.value() if scroll_bar else 0
        viewport_bottom = viewport_top + viewport_height
        
        # Add margin for preloading
        preload_margin = 500  # Preload 500px above and below viewport
        visible_top = viewport_top - preload_margin
        visible_bottom = viewport_bottom + preload_margin
        
        visible_paths = []
        for row_item in self.rows:
            if row_item.rect:
                row_top = row_item.rect.y()
                row_bottom = row_top + row_item.rect.height()
                # Include row if it intersects visible area (with preload margin)
                if row_bottom >= visible_top and row_top <= visible_bottom:
                    # Only request if not already loaded
                    if not row_item.pixmap or row_item.pixmap.isNull():
                        visible_paths.append(row_item.image_path)
        
        # Request thumbnails - use current row height for list view
        if visible_paths and cache_manager:
            # Request thumbnails at current row height - they'll be scaled to 2x height when displayed
            current_thumb_size = self.row_height
            for image_path in visible_paths:
                # Request thumbnail - will use cache if available
                # Use higher priority (2) for list view to ensure they load quickly
                try:
                    cache_manager.get_thumbnail_async(image_path, current_thumb_size, priority=2)
                except Exception:
                    # Silently continue if request fails
                    pass
    
    def on_thumbnail_loaded(self, image_path: str, pixmap: QPixmap, size: int):
        """Handle thumbnail loaded signal"""
        if not pixmap or pixmap.isNull():
            return
        
        # Normalize paths for comparison (handle relative vs absolute paths)
        try:
            normalized_path = os.path.abspath(os.path.expanduser(image_path))
        except Exception:
            normalized_path = image_path
        
        updated = False
        update_rect = None
        
        with QMutexLocker(self.mutex):
            # Safety check: if rows list is empty, skip update
            if not self.rows:
                return
            
            # Find matching row by comparing paths (exact match first, then normalized)
            for row_item in self.rows:
                # Try exact match first (fastest)
                if row_item.image_path == image_path:
                    row_item.pixmap = pixmap
                    row_item.is_loading = False
                    updated = True
                    update_rect = row_item.rect
                    break
                
                # Try normalized path comparison
                try:
                    row_path_normalized = os.path.abspath(os.path.expanduser(row_item.image_path))
                    if (row_path_normalized == normalized_path or
                        row_path_normalized == image_path or
                        row_item.image_path == normalized_path):
                        row_item.pixmap = pixmap
                        row_item.is_loading = False
                        updated = True
                        update_rect = row_item.rect
                        break
                except Exception:
                    # If normalization fails, skip this row
                    continue
        
        # Update the row if it was found
        if updated and update_rect:
            self.update(update_rect)
    
    def mousePressEvent(self, event: QMouseEvent):
        """Handle mouse press events"""
        if event.button() == Qt.LeftButton:
            row_index = self._get_row_at_position(event.pos())
            if row_index is not None:
                # Cache modifiers() result to avoid calling it twice (prevents KeyboardModifier warnings)
                modifiers = event.modifiers()
                # On macOS: ControlModifier=Command(⌘) for multiselect, MetaModifier=Control(⌃) for context menu
                cmd_pressed = bool(modifiers & Qt.ControlModifier)
                shift_pressed = bool(modifiers & Qt.ShiftModifier)
                macos_ctrl_pressed = bool(modifiers & Qt.MetaModifier)
                
                # Store click data for delayed processing (to allow double-click detection)
                self._pending_click_data = (row_index, cmd_pressed, shift_pressed, macos_ctrl_pressed)
                self._single_click_timer.start(250)  # 250ms delay for double-click detection
            event.accept()
        else:
            super().mousePressEvent(event)

    def contextMenuEvent(self, event: QContextMenuEvent):
        """Handle right-click / Control+click (macOS) - show context menu only for Ctrl, not Cmd.
        Cmd+click (ControlModifier) = multiselect; Ctrl+click (MetaModifier) or right-click = context menu."""
        # On macOS: ControlModifier=Cmd - do NOT show context menu (reserved for multiselect)
        if event.modifiers() & Qt.ControlModifier:
            event.accept()
            return
        row_index = self._get_row_at_position(event.pos())
        if row_index is not None:
            # Right-click or Ctrl+click - request context menu (macos_ctrl_pressed=True)
            self.thumbnail_clicked.emit(row_index, False, False, True)
        event.accept()

    def _handle_delayed_single_click(self):
        """Handle delayed single click (if not double-clicked)"""
        if self._pending_click_data:
            row_index, cmd_pressed, shift_pressed, macos_ctrl_pressed = self._pending_click_data
            self.thumbnail_clicked.emit(row_index, cmd_pressed, shift_pressed, macos_ctrl_pressed)
            self._pending_click_data = None
    
    def mouseDoubleClickEvent(self, event: QMouseEvent):
        """Handle double click events"""
        if event.button() == Qt.LeftButton:
            self._single_click_timer.stop()
            self._pending_click_data = None
            
            row_index = self._get_row_at_position(event.pos())
            if row_index is not None:
                self.thumbnail_double_clicked.emit(row_index)
            event.accept()
        else:
            super().mouseDoubleClickEvent(event)
    
    def keyPressEvent(self, event: QKeyEvent):
        """Handle key press events - forward to main window for navigation"""
        # CRITICAL: Only handle events if we're actually in list view mode
        # This prevents stale events from interfering when switching back to thumbnail view
        if hasattr(self.main_window, 'current_view_mode') and self.main_window.current_view_mode != 'list':
            # Not in list view mode - forward immediately without local handling
            if hasattr(self.main_window, 'keyPressEvent'):
                self.main_window.keyPressEvent(event)
                return
            else:
                super().keyPressEvent(event)
                return
        
        key = event.key()
        
        # Handle PageUp/PageDown for scrolling the list view
        if key in [Qt.Key_PageUp, Qt.Key_PageDown]:
            # Get scroll area from parent
            scroll_area = None
            parent = self.parent()
            while parent:
                if hasattr(parent, 'scroll_area'):
                    scroll_area = parent.scroll_area
                    break
                parent = parent.parent()
            
            if scroll_area:
                scroll_bar = scroll_area.verticalScrollBar()
                if scroll_bar:
                    viewport_height = scroll_area.viewport().height()
                    if key == Qt.Key_PageUp:
                        scroll_bar.setValue(max(0, scroll_bar.value() - viewport_height))
                    else:  # PageDown
                        scroll_bar.setValue(min(scroll_bar.maximum(), scroll_bar.value() + viewport_height))
                    event.accept()
                    return
        
        # Forward arrow keys to main window for navigation handling
        # Don't accept here - let main window handle and accept if needed
        if hasattr(self.main_window, 'keyPressEvent'):
            self.main_window.keyPressEvent(event)
            # If main window handled it, the event will be accepted
            # If not, we still want to prevent default behavior
            if event.isAccepted():
                return
        else:
            super().keyPressEvent(event)
    
    def focusNextPrevChild(self, next: bool) -> bool:
        """Prevent Tab key from navigating to/from this widget"""
        return False  # Don't participate in tab order
    
    def paintDropIndicator(self, painter: QPainter):
        """Paint drop indicator if dragging"""
        if self._show_drop_indicator and self._current_insertion_index is not None:
            # Draw insertion line - use darker color for list view
            _bw = max(1, min(int(getattr(tc, "MAX_THEME_BORDER_WIDTH_PX", 10)), int(getattr(tc, "CURRENT_IMAGE_BORDER_WIDTH_PX", 2))))
            painter.setPen(QPen(tc.CURRENT_IMAGE_BORDER_COLOR, _bw))
            # Calculate position based on insertion index
            if 0 <= self._current_insertion_index < len(self.rows):
                row_item = self.rows[self._current_insertion_index]
                if row_item.rect:
                    y = row_item.rect.top()
                    painter.drawLine(BASE_MARGIN, y, self.get_viewport_width() - BASE_MARGIN, y)
    
    def dragEnterEvent(self, event: QDragEnterEvent):
        """Handle drag enter events"""
        if event.mimeData().hasUrls() or event.mimeData().hasFormat(self.MIME_TYPE):
            event.acceptProposedAction()
            self._show_drop_indicator = True
            self.update()
    
    def dragLeaveEvent(self, event: QDragLeaveEvent):
        """Handle drag leave events"""
        self._show_drop_indicator = False
        self._current_insertion_index = None
        self.update()
    
    def dragMoveEvent(self, event: QDragMoveEvent):
        """Handle drag move events"""
        if event.mimeData().hasUrls() or event.mimeData().hasFormat(self.MIME_TYPE):
            event.acceptProposedAction()
            # Find insertion point
            pos = event.pos()
            row_index = self._get_row_at_position(pos)
            if row_index is not None:
                # Insert after the row
                self._current_insertion_index = row_index + 1
            else:
                self._current_insertion_index = len(self.rows)
            self.update()
    
    def dropEvent(self, event: QDropEvent):
        """Handle drop events"""
        self._show_drop_indicator = False
        self._current_insertion_index = None
        # Forward to main window for handling
        if hasattr(self.main_window, 'dropEvent'):
            self.main_window.dropEvent(event)
        self.update()
    
    def increase_row_height(self):
        """Increase row height by 4px (max 64px)"""
        new_height = min(MAX_ROW_HEIGHT, self.row_height + 4)
        if new_height != self.row_height:
            self._set_row_height(new_height)
    
    def decrease_row_height(self):
        """Decrease row height by 4px (min 28px)"""
        new_height = max(28, self.row_height - 4)
        if new_height != self.row_height:
            self._set_row_height(new_height)
    
    def reset_row_height(self):
        """Reset row height to default (48px)"""
        self._set_row_height(48)
    
    def _set_row_height(self, new_height: int):
        """Set row height and update all related sizes"""
        self.row_height = new_height
        
        # Update thumbnail width (2x height)
        self.column_widths['thumbnail'] = 2 * self.row_height
        
        # Recreate placeholder pixmap with new size
        thumbnail_width = 2 * self.row_height
        self._placeholder_pixmap = QPixmap(thumbnail_width, self.row_height)
        if self._placeholder_pixmap.isNull():
            self._placeholder_pixmap = QPixmap(max(1, thumbnail_width), max(1, self.row_height))
        # Fill with gray and draw border
        self._placeholder_pixmap.fill(QColor(80, 80, 80))
        from PySide6.QtGui import QPainter as QPixmapPainter
        pixmap_painter = QPixmapPainter(self._placeholder_pixmap)
        pixmap_painter.setPen(QPen(QColor(120, 120, 120), 2))
        pixmap_painter.drawRect(0, 0, thumbnail_width - 1, self.row_height - 1)
        pixmap_painter.end()
        
        # Save to config
        from config import get_config
        config = get_config()
        config.update_setting('list_view_row_height', self.row_height)
        
        # Update header height if manager exists
        if hasattr(self.main_window, 'list_view_container') and self.main_window.list_view_container:
            header_widget = self.main_window.list_view_container.header_widget
            if header_widget:
                header_widget.setFixedHeight(self.row_height)
        
        # Clear cached column positions
        self._cached_col_x = None
        self._cached_row_width = None
        
        # Update row rectangles and refresh
        self._update_row_rectangles()
        self.update()
        
        # Trigger thumbnail reload with new size
        QTimer.singleShot(100, self._load_visible_thumbnails)
