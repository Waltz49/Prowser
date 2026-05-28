#!/usr/bin/env python3
"""
List Canvas Manager for Image Browser
Manages the canvas-based list view display and integrates with the existing image browser system
"""

# Standard library imports
from typing import List, Optional, Set, Tuple

# Third-party imports
from PySide6.QtCore import QEvent, QMutexLocker, QPoint, Qt, QTimer
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication, QScrollArea, QVBoxLayout, QWidget

# Local imports
from list_canvas import ListCanvas
from sort_mode import SortMode
import thumbnail_constants as tc
from thumbnail_constants import CANVAS_TOP_MARGIN, BASE_MARGIN

class ListHeaderWidget(QWidget):
    """Fixed header widget that doesn't scroll"""
    
    def __init__(self, canvas, parent=None):
        super().__init__(parent)
        self.canvas = canvas
        # Use canvas row height for header height
        self.setFixedHeight(canvas.row_height)
        self.setFocusPolicy(Qt.NoFocus)
        # Enable mouse tracking for hover effects (optional)
        self.setMouseTracking(True)
    
    def _get_column_at_position(self, pos: QPoint) -> Optional[str]:
        """Get the column key at the given position"""
        # Get actual row width from canvas if available
        actual_row_width = None
        if self.canvas.rows:
            first_row = self.canvas.rows[0]
            if first_row.rect and first_row.rect.isValid():
                actual_row_width = first_row.rect.width()
        
        if actual_row_width is None or actual_row_width <= 0:
            canvas_width = self.width()
            if canvas_width <= 0:
                canvas_width = 1200
            actual_row_width = max(100, canvas_width - (BASE_MARGIN * 2))
        
        col_x = self.canvas._calculate_column_positions(row_width=actual_row_width)
        
        x = pos.x()
        
        # Check each column (in reverse order so name column is checked last)
        columns = ['name', 'dimensions', 'size', 'date', 'permissions', 'thumbnail']
        for col_key in columns:
            x_pos = col_x[col_key]
            if col_key == 'name':
                col_width = col_x.get('name_width', actual_row_width - (x_pos - BASE_MARGIN))
            else:
                col_width = self.canvas.column_widths[col_key]
            
            if x_pos <= x < x_pos + col_width:
                return col_key
        
        return None
    
    def _get_sort_mode_for_column(self, col_key: str) -> Optional[SortMode]:
        """Map column key to sort mode"""
        mapping = {
            'date': SortMode.DATE,
            'size': SortMode.FILESIZE,  # File size, not area
            'dimensions': SortMode.DIMENSIONS,
            'name': SortMode.NAME,
            'permissions': SortMode.PERMISSIONS,
        }
        return mapping.get(col_key)
    
    def mousePressEvent(self, event: QMouseEvent):
        """Handle mouse press events on header"""
        if event.button() == Qt.LeftButton:
            col_key = self._get_column_at_position(event.pos())
            if col_key:
                sort_mode = self._get_sort_mode_for_column(col_key)
                if sort_mode and hasattr(self.canvas, 'main_window'):
                    main_window = self.canvas.main_window
                    if hasattr(main_window, 'sorting_manager'):
                        # Check if this is the current sort mode
                        current_mode = main_window.sorting_manager.get_current_sort_mode()
                        toggle_reverse = (current_mode == sort_mode)
                        
                        # Set sort mode (will toggle if same column)
                        # This will call apply_current_sort() which updates the list view if needed
                        main_window.sorting_manager.set_sort_mode(sort_mode, toggle_reverse=toggle_reverse)
                        
                        # Update header to show sort indicator
                        self.update()
            event.accept()
        else:
            super().mousePressEvent(event)
    
    def paintEvent(self, event):
        """Paint the header"""
        from PySide6.QtGui import QPainter, QColor, QFont, QPen
        from PySide6.QtCore import QRect
        
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        try:
            # Get the actual row width from canvas to ensure perfect alignment
            # The canvas has rows with rects that define the actual table width
            actual_row_width = None
            if self.canvas.rows:
                # Get row width from first row's rect if available
                first_row = self.canvas.rows[0]
                if first_row.rect and first_row.rect.isValid():
                    actual_row_width = first_row.rect.width()
            
            # Fallback to calculated width if rows not available yet
            if actual_row_width is None or actual_row_width <= 0:
                canvas_width = self.width()
                if canvas_width <= 0:
                    canvas_width = 1200
                actual_row_width = max(100, canvas_width - (BASE_MARGIN * 2))
            
            # Calculate column positions using the actual row width
            col_x = self.canvas._calculate_column_positions(row_width=actual_row_width)
            
            # Draw header background only for sortable columns
            # Background starts at the vertical line after thumbnail (not at permissions column start)
            # This line is at: col_x['thumbnail'] + column_widths['thumbnail']
            header_y = 0
            header_height = self.canvas.row_height
            
            # Start at the line position (where the vertical separator is drawn)
            sortable_start_x = col_x['thumbnail'] + self.canvas.column_widths['thumbnail']
            
            # End at the right border line position (rect.right() in rows)
            # This is BASE_MARGIN + row_width, which equals rect.right()
            sortable_end_x = BASE_MARGIN + actual_row_width
            
            # Draw background rectangle for sortable columns only
            bg_rect = QRect(sortable_start_x, header_y, sortable_end_x - sortable_start_x, header_height)
            painter.fillRect(bg_rect, QColor(50, 50, 50))
            
            # Get current sort mode and direction
            current_sort_mode = None
            is_reversed = False
            if hasattr(self.canvas, 'main_window'):
                main_window = self.canvas.main_window
                if hasattr(main_window, 'sorting_manager'):
                    current_sort_mode = main_window.sorting_manager.get_current_sort_mode()
                    is_reversed = main_window.sorting_manager.sort_direction_reversed
            
            # Map sort mode to column key
            sort_mode_to_col = {
                SortMode.DATE: 'date',
                SortMode.FILESIZE: 'size',
                SortMode.DIMENSIONS: 'dimensions',
                SortMode.NAME: 'name',
                SortMode.PERMISSIONS: 'permissions',
            }
            sorted_col_key = sort_mode_to_col.get(current_sort_mode)
            
            # Draw header text - white color
            painter.setPen(QColor(255, 255, 255))  # White text
            font = QFont("Arial", 13)
            font.setBold(True)
            painter.setFont(font)
            
            headers = [
                ('thumbnail', ''),
                ('permissions', 'Perm'),
                ('date', 'Date'),
                ('size', 'Size'),
                ('dimensions', 'Dim'),
                ('name', 'Name')
            ]
            
            # header_y and header_height already set above
            
            for col_key, header_text in headers:
                x_pos = col_x[col_key]
                if col_key == 'name':
                    col_width = col_x.get('name_width', actual_row_width - (x_pos - BASE_MARGIN))
                    align = Qt.AlignLeft | Qt.AlignVCenter
                else:
                    col_width = self.canvas.column_widths[col_key]
                    align = Qt.AlignCenter | Qt.AlignVCenter
                
                if col_width > 0:
                    # Ensure white pen is set before drawing each text
                    painter.setPen(QColor(255, 255, 255))  # White text
                    header_text_rect = QRect(x_pos, header_y, col_width, header_height)
                    
                    # Draw header text with sort indicator if this is the sorted column
                    if col_key == sorted_col_key:
                        # Calculate text width to position caret
                        font_metrics = painter.fontMetrics()
                        text_width = font_metrics.horizontalAdvance(header_text)
                        
                        # Position caret after text (with small spacing)
                        caret_x = x_pos
                        if align & Qt.AlignLeft:
                            # Left aligned: caret after text
                            caret_x = x_pos + text_width + 4
                        elif align & Qt.AlignCenter:
                            # Center aligned: caret after centered text
                            text_start_x = x_pos + (col_width - text_width) // 2
                            caret_x = text_start_x + text_width + 4
                        elif align & Qt.AlignRight:
                            # Right aligned: caret before text
                            caret_x = x_pos + col_width - text_width - 4
                        caret_x += 5
                        # Draw text first
                        painter.drawText(header_text_rect, align, header_text)
                        
                        # Draw sort indicator (caret)
                        caret_y = header_y + header_height // 2
                        caret_size = 6
                        
                        # Draw caret (^ for ascending, v for descending)
                        from PySide6.QtGui import QPen
                        pen = QPen(QColor(255, 255, 255))
                        pen.setWidth(2)  # Double the default line thickness (usually 1)
                        painter.setPen(pen)
                        narrower = caret_size - 1  # 2 px narrower (caret_size is 6; now becomes 5)
                        if is_reversed:
                            # Descending: draw v (down arrow)
                            painter.drawLine(caret_x - narrower, caret_y - caret_size // 2, 
                                             caret_x, caret_y + caret_size // 2)
                            painter.drawLine(caret_x, caret_y + caret_size // 2,
                                             caret_x + narrower, caret_y - caret_size // 2)
                        else:
                            # Ascending: draw ^ (up arrow)
                            painter.drawLine(caret_x - narrower, caret_y + caret_size // 2,
                                             caret_x, caret_y - caret_size // 2)
                            painter.drawLine(caret_x, caret_y - caret_size // 2,
                                             caret_x + narrower, caret_y + caret_size // 2)
                    painter.drawText(header_text_rect, align, header_text)
                    
                    # For name column, add directory notation (right-justified, small font)
                    if col_key == 'name':
                        # Get displayed images to determine directory
                        directory_text = None
                        if hasattr(self.canvas, 'main_window'):
                            main_window = self.canvas.main_window
                            if hasattr(main_window, 'displayed_images') and main_window.displayed_images:
                                displayed_images = main_window.displayed_images
                                # Get directories of all displayed files
                                directories = set()
                                import os
                                for image_path in displayed_images:
                                    if image_path:
                                        try:
                                            abs_path = os.path.abspath(os.path.expanduser(image_path))
                                            if os.path.exists(abs_path):
                                                file_dir = os.path.dirname(abs_path)
                                                directories.add(file_dir)
                                        except (OSError, ValueError):
                                            continue
                                
                                # If all files are from the same directory, show it
                                if len(directories) == 1:
                                    directory_path = directories.pop()
                                    # Use normalize_path_for_display to convert ~ for home dir
                                    from utils import normalize_path_for_display
                                    directory_text = normalize_path_for_display(directory_path)
                                else:
                                    directory_text = "Multiple directories"
                            
                            # Draw directory notation if available
                            if directory_text:
                                # Calculate space needed for "Name" text and caret (if sorted)
                                # Use the header font metrics to measure "Name" text width
                                header_font_metrics = painter.fontMetrics()
                                name_text_width = header_font_metrics.horizontalAdvance(header_text)
                                
                                # If this column is sorted, account for caret width
                                caret_width = 0
                                if col_key == sorted_col_key:
                                    # Caret is positioned after text with spacing
                                    # caret_x calculation: x_pos + text_width + 4 + 5, then caret_size (6) + some margin
                                    caret_width = 15  # Approximate: spacing (4+5) + caret size (6) + margin
                                
                                # Calculate available width: column width - name text - caret - right margin
                                right_margin = 30
                                left_space_needed = name_text_width + caret_width + 10  # 10px spacing between name and directory
                                directory_width = col_width - left_space_needed - right_margin
                                
                                # Ensure directory width is positive
                                if directory_width > 0:
                                    # Use smaller font for directory notation (increased from 10 to 11)
                                    small_font = QFont("Arial", 14)
                                    small_font.setBold(False)
                                    painter.setFont(small_font)
                                    # painter.setPen(QColor(200, 200, 200))  # Slightly dimmer than header text
                                    painter.setPen(QColor(200, 200, 250))  # Slightly dimmer than header text
                                    
                                    # Right-justified with 30px right margin, left-elided
                                    # Rectangle ends 30px before the right edge of the column
                                    directory_rect = QRect(x_pos, header_y, col_width - right_margin, header_height)
                                    small_font_metrics = painter.fontMetrics()
                                    # Elide from left if necessary, using the calculated available width
                                    elided_text = small_font_metrics.elidedText(directory_text, Qt.ElideLeft, directory_width)
                                    painter.drawText(directory_rect, Qt.AlignRight | Qt.AlignVCenter, elided_text)
                                    
                                    # Reset font and pen for next column
                                    painter.setFont(font)
                                    painter.setPen(QColor(255, 255, 255))
                    
                    # Draw vertical separator line after this column (except after thumbnail and name)
                    # Skip thumbnail column (first column) and name column (last column)
                    if col_key != 'name' and col_key != 'thumbnail':
                        line_x = x_pos + col_width
                        painter.setPen(QPen(tc.DEFAULT_BORDER_COLOR, 1))
                        painter.drawLine(line_x, header_y, line_x, header_y + header_height)
                        # Reset pen to white for next text
                        painter.setPen(QColor(255, 255, 255))
            
            # Left and right border lines removed per user request
        finally:
            painter.end()

class ListCanvasManager(QWidget):
    """
    Manager for the canvas-based list view display.
    Similar to CanvasManager but for list view.
    """
    
    def __init__(self, main_window, parent=None):
        super().__init__(parent)
        self.main_window = main_window
        
        # Create the canvas (without header - header will be separate)
        self.canvas = ListCanvas(main_window, self)
        
        # Create fixed header widget
        self.header_widget = ListHeaderWidget(self.canvas, self)
        
        # Create scroll area (only for canvas, not header)
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(False)  # Let canvas control its own size
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.scroll_area.setFocusPolicy(Qt.NoFocus)
        
        # Override scroll area keyPressEvent to prevent arrow keys from scrolling
        # Arrow keys should be handled by canvas for navigation, not scrolling
        def scroll_area_keyPressEvent(event):
            key = event.key()
            # Don't let scroll area handle arrow keys - forward to canvas
            if key in [Qt.Key_Up, Qt.Key_Down, Qt.Key_Left, Qt.Key_Right]:
                # Forward to canvas which will forward to main window
                if self.canvas:
                    self.canvas.keyPressEvent(event)
                event.accept()
                return
            # Let scroll area handle other keys (like PageUp/PageDown for scrolling)
            QScrollArea.keyPressEvent(self.scroll_area, event)
        
        self.scroll_area.keyPressEvent = scroll_area_keyPressEvent
        
        # Set the canvas directly as the scroll area's widget
        self.scroll_area.setWidget(self.canvas)
        
        # Set minimum size for the canvas
        self.canvas.setMinimumSize(200, 200)
        
        # Set focus policy - allow canvas to receive focus for keyboard events
        self.setFocusPolicy(Qt.NoFocus)  # Manager itself doesn't need focus
        self.canvas.setFocusPolicy(Qt.ClickFocus)  # Canvas needs focus but not via Tab key
        
        # Create main layout with header on top
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.header_widget)  # Fixed header
        layout.addWidget(self.scroll_area)  # Scrollable content
        
        # Connect canvas signals to main window
        self._connect_signals()
        
        # Connect scroll signals for lazy thumbnail loading
        self.scroll_area.verticalScrollBar().valueChanged.connect(self._on_scroll_changed)
        
        # Connect horizontal scroll to sync header
        self.scroll_area.horizontalScrollBar().valueChanged.connect(self._sync_header_scroll)
        
        # Connect scroll area viewport resize to update list view
        self.scroll_area.viewport().installEventFilter(self)
    
    def eventFilter(self, obj, event):
        """Filter events to handle viewport resize"""
        if obj == self.scroll_area.viewport() and event.type() == QEvent.Resize:
            # Viewport was resized - update row rectangles and header
            QTimer.singleShot(10, self._handle_viewport_resize)
        return super().eventFilter(obj, event)
    
    def _handle_viewport_resize(self):
        """Handle viewport resize - update row rectangles and header"""
        if self.canvas.rows:
            # Clear cached column positions
            self.canvas._cached_col_x = None
            self.canvas._cached_row_width = None
            # Update row rectangles
            self.canvas._update_row_rectangles()
            # Update canvas and header
            self.canvas.update()
            self.header_widget.update()
    
    def resizeEvent(self, event):
        """Handle resize events - update row rectangles and header"""
        super().resizeEvent(event)
        # Delay update to allow Qt to finish layout updates
        QTimer.singleShot(10, self._handle_viewport_resize)
    
    def _sync_header_scroll(self):
        """Sync header horizontal scroll with canvas scroll"""
        # Header doesn't scroll horizontally - it's fixed
        # But we need to update it when canvas width changes
        self.header_widget.update()
    
    def _connect_signals(self):
        """Connect canvas signals to main window methods"""
        self.canvas.thumbnail_clicked.connect(self._on_row_clicked)
        self.canvas.thumbnail_double_clicked.connect(self._on_row_double_clicked)
        
        # Connect thumbnail loading signals from cache manager
        self.connect_cache_manager_signals()
    
    def connect_cache_manager_signals(self):
        """Connect to cache manager signals when available"""
        if hasattr(self.main_window, 'cache_manager') and self.main_window.cache_manager:
            try:
                import warnings
                signal = self.main_window.cache_manager.thumbnail_ready
                # Disconnect first to avoid duplicates (try/catch handles case where not connected)
                # Suppress RuntimeWarning about failed disconnect
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore", RuntimeWarning)
                    try:
                        signal.disconnect(self.canvas.on_thumbnail_loaded)
                    except (TypeError, RuntimeError):
                        # Signal not connected to this slot - this is OK
                        pass
                # Connect with QueuedConnection for thread safety
                signal.connect(self.canvas.on_thumbnail_loaded, Qt.QueuedConnection)
            except Exception:
                pass
    
    def _on_row_clicked(self, index: int, cmd_pressed: bool, shift_pressed: bool, macos_ctrl_pressed: bool):
        """Handle row click from canvas - emit event for subscriber to handle"""
        from event_bus import THUMBNAIL_CLICKED
        if hasattr(self.main_window, 'event_bus') and self.main_window.event_bus:
            self.main_window.event_bus.emit(THUMBNAIL_CLICKED, (index, cmd_pressed, shift_pressed, macos_ctrl_pressed))
        elif hasattr(self.main_window, 'navigation_manager'):
            self.main_window.navigation_manager.handle_thumbnail_click(index, cmd_pressed, shift_pressed, macos_ctrl_pressed)
    
    def _on_row_double_clicked(self, index: int):
        """Handle row double-click from canvas"""
        # Get the file path from the row
        if (hasattr(self.main_window, 'displayed_images') and 
            self.main_window.displayed_images and
            0 <= index < len(self.main_window.displayed_images)):
            image_path = self.main_window.displayed_images[index]
            
            # Set current image path
            if hasattr(self.main_window, '_set_current_image_path_with_sync'):
                self.main_window._set_current_image_path_with_sync(image_path)
            else:
                self.main_window.current_image_path = image_path
            
            # CRITICAL: Set flag to return to list view since we're clicking from list view
            # This ensures we return to list mode after closing browse view
            self.main_window._return_to_list_view = True
            
            # Open browse view
            if hasattr(self.main_window, 'view_mode_manager'):
                self.main_window.view_mode_manager.open_browse_view(index)
    
    def _on_scroll_changed(self):
        """Handle scroll change - trigger lazy thumbnail loading"""
        if hasattr(self.canvas, '_load_visible_thumbnails'):
            self.canvas._load_visible_thumbnails()
    
    def set_rows(self, image_paths: List[str], row_data: List[Tuple[str, str, str, str, str]]):
        """Set the rows to display in list view"""
        # Ensure scroll area has a proper size before setting rows
        viewport = self.scroll_area.viewport()
        if viewport.width() < 200:
            # Try to get size from parent or use default
            parent_width = self.width() if self.width() > 0 else 800
            parent_height = self.height() if self.height() > 0 else 600
            viewport.resize(max(parent_width, 800), max(parent_height, 600))
        
        self.canvas.set_rows(image_paths, row_data)
        
        # Update header to match canvas width
        self.header_widget.update()
        
        # Force update after a short delay to ensure widget is visible and sized
        QTimer.singleShot(100, lambda: (
            self.canvas.show(),
            self.canvas.setVisible(True),
            self.canvas._update_row_rectangles(),
            self.canvas.update(),
            self.header_widget.update(),
            QApplication.processEvents()
        ))
        
        # Ensure cache manager signals are connected and trigger thumbnail loading
        QTimer.singleShot(300, lambda: (
            self.connect_cache_manager_signals(),
            self.canvas._load_visible_thumbnails()
        ))
    
    def set_highlighted_index(self, index: int):
        """Set the highlighted row index"""
        self.canvas.highlighted_index = index
        self.canvas.update()
    
    def set_selected_indices(self, indices: Set[int]):
        """Set the selected row indices"""
        self.canvas.selected_indices = indices
        self.canvas.update()
    
    def set_multi_select_mode(self, enabled: bool):
        """Set multi-select mode"""
        self.canvas.multi_select_mode = enabled
    
    def scroll_to_highlighted(self, index: int = None, force: bool = False):
        """Scroll to the highlighted row only if it's not already fully visible
        
        Args:
            index: Row index to scroll to (defaults to highlighted_index)
            force: If True, always scroll even if row is already visible (useful for H/E keys)
        """
        if index is None:
            index = self.canvas.highlighted_index
        
        if index < 0 or index >= len(self.canvas.rows):
            return
        
        # Ensure row rectangles are updated before scrolling
        if hasattr(self.canvas, '_update_row_rectangles'):
            self.canvas._update_row_rectangles()
        
        row_item = self.canvas.rows[index]
        if not row_item.rect:
            # If rect is not set, try updating again after a short delay
            from PySide6.QtCore import QTimer
            QTimer.singleShot(10, lambda: self.scroll_to_highlighted(index, force))
            return
        
        scroll_bar = self.scroll_area.verticalScrollBar()
        if not scroll_bar:
            return
        
        # Get viewport dimensions
        viewport = self.scroll_area.viewport()
        viewport_height = viewport.height()
        viewport_top = scroll_bar.value()
        viewport_bottom = viewport_top + viewport_height
        
        # Get row position (relative to canvas)
        row_top = row_item.rect.y()
        row_bottom = row_top + row_item.rect.height()
        
        # Check if entire row is already fully visible in viewport (unless forcing scroll)
        if not force:
            # Row is fully visible if both top and bottom are within viewport bounds
            if row_top >= viewport_top and row_bottom <= viewport_bottom:
                # Row is already fully visible, no need to scroll
                return
        
        # Row is not fully visible or force scroll - scroll just enough to make it visible
        # Calculate how much we need to scroll
        if force:
            # Force scroll: scroll to show row at top with small margin
            margin = 5
            target_scroll = max(0, row_top - margin)
        elif row_top < viewport_top:
            # Row top is above viewport - scroll up just enough to show the top
            # Don't scroll to top of screen, just enough to make row visible
            target_scroll = max(0, row_top)
        elif row_bottom > viewport_bottom:
            # Row bottom is below viewport - scroll down just enough to show the bottom
            # Calculate scroll position so row bottom is at viewport bottom
            target_scroll = max(0, row_bottom - viewport_height)
        else:
            # This shouldn't happen if our visibility check is correct, but handle it
            return
        
        # Ensure we don't scroll beyond maximum
        max_scroll = scroll_bar.maximum()
        target_scroll = min(target_scroll, max_scroll)
        scroll_bar.setValue(target_scroll)
    
    def update(self):
        """Update the canvas"""
        self.canvas.update()
    
    def show(self):
        """Show the list canvas manager"""
        super().show()
        self.canvas.show()
        # Give focus to canvas so keyboard events work
        QTimer.singleShot(50, lambda: self.canvas.setFocus())
    
    def hide(self):
        """Hide the list canvas manager"""
        super().hide()
        self.canvas.hide()
    
    # Compatibility methods for drag and drop
    def setAcceptDrops(self, enabled: bool):
        """Enable/disable drag and drop"""
        self.canvas.setAcceptDrops(enabled)
    
    def dragEnterEvent(self, event):
        """Handle drag enter events"""
        self.canvas.dragEnterEvent(event)
    
    def dragMoveEvent(self, event):
        """Handle drag move events"""
        self.canvas.dragMoveEvent(event)
    
    def dragLeaveEvent(self, event):
        """Handle drag leave events"""
        self.canvas.dragLeaveEvent(event)
    
    def dropEvent(self, event):
        """Handle drop events"""
        self.canvas.dropEvent(event)
