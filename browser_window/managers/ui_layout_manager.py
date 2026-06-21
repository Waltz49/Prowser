#!/usr/bin/env python3
"""
UI Layout Manager
Handles UI setup, layout management, and widget positioning
"""

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QResizeEvent
from PySide6.QtWidgets import QApplication


class UILayoutManager:
    """Manages UI layout and widget positioning"""
    
    def __init__(self, main_window):
        """
        Initialize the UI layout manager
        
        Args:
            main_window: Reference to the main ImageBrowserWindow instance
        """
        self.main_window = main_window
        if hasattr(main_window, 'event_bus') and main_window.event_bus:
            from event_bus import VIEW_MODE_CHANGED
            main_window.event_bus.subscribe(VIEW_MODE_CHANGED, self._on_view_mode_changed)
        
        # Debounce timer for sidebar resize to avoid excessive thumbnail layout recalculations
        self._sidebar_resize_timer = QTimer()
        self._sidebar_resize_timer.setSingleShot(True)
        self._sidebar_resize_timer.timeout.connect(self._on_sidebar_resize_debounced)
        
        # Track sidebar width for detecting significant resize changes
        self._last_sidebar_width = None

    def _on_view_mode_changed(self, mode: str):
        """Handle VIEW_MODE_CHANGED - refresh layout when view mode changes"""
        if mode == 'browse' and hasattr(self.main_window, '_resize_browse_view_image_container'):
            QTimer.singleShot(50, self.main_window._resize_browse_view_image_container)
        elif mode == 'thumbnail':
            # During browse exit, defer refresh so sidebar has time to show (avoids refresh before tree visible)
            if getattr(self.main_window, 'browse_view_exit_in_progress', False):
                QTimer.singleShot(50, self._immediate_splitter_update)
            else:
                self._immediate_splitter_update()
    
    def _on_splitter_moved(self, pos, index):
        """Handle splitter resize to update thumbnail layout when sidebar width changes"""
        
        # Skip if we're suppressing splitter moved events (during programmatic changes)
        if hasattr(self.main_window, '_suppress_splitter_moved') and self.main_window._suppress_splitter_moved:
            return
        
        # Respond to splitter movement for both sidebars
        # Index 0: left sidebar, Index 1: main content, Index 2: right sidebar
        sizes = self.main_window.main_splitter.sizes()
        
        if index == 0:  # Left sidebar moved
            if sizes[0] > 0:  # Sidebar is visible
                self.main_window.sidebar_width = sizes[0]
                self.main_window.config.update_setting('sidebar_width', self.main_window.sidebar_width)
        elif index == 1:  # Main content handle moved - user dragged LEFT sidebar handle
            # When main content handle moves, it means user dragged the LEFT sidebar handle
            # Save the new left sidebar width - this is a USER ACTION, not Qt recalculation
            if sizes[0] > 0:  # Sidebar is visible
                self.main_window.sidebar_width = sizes[0]
                self.main_window.config.update_setting('sidebar_width', self.main_window.sidebar_width)
        elif index == 2:  # Right sidebar moved
            if sizes[2] > 0:  # Right sidebar is visible
                self.main_window.right_sidebar_width = sizes[2]
                # Save the right sidebar width
                self.main_window.config.update_setting('right_sidebar_width', self.main_window.right_sidebar_width)
                # Ensure sidebar is marked as visible
                if not hasattr(self.main_window, 'right_sidebar_visible') or not self.main_window.right_sidebar_visible:
                    self.main_window.right_sidebar_visible = True
                    self.main_window.config.update_setting('right_sidebar_visible', True)
            
            # Ensure at least one column of thumbnails is visible
            min_thumb_width = 200
            available_width = sizes[1]  # Main content width
            if available_width < min_thumb_width:
                # Adjust right sidebar to ensure minimum thumbnail width
                total_width = sum(sizes)
                new_right_width = max(0, total_width - sizes[0] - min_thumb_width)
                new_main_width = total_width - sizes[0] - new_right_width
                self.main_window.main_splitter.setSizes([sizes[0], new_main_width, new_right_width])
                self.main_window.right_sidebar_width = new_right_width
                self.main_window.config.update_setting('right_sidebar_width', self.main_window.right_sidebar_width)
        
        # Handle browse mode - resize image container when any sidebar is resized
        # Delay to allow Qt to finish updating the layout before recalculating fit-to-screen
        if (index == 0 or index == 2) and self.main_window.current_view_mode == 'browse':
            QTimer.singleShot(50, self.main_window._resize_browse_view_image_container)
            
            # Update info text width if right_sidebar was resized
            right_sb = getattr(self.main_window, 'right_sidebar', None)
            info_edit = getattr(right_sb, 'info_text_edit', None) if right_sb else None
            if index == 2 and info_edit and info_edit.isVisible():
                def update_info_width():
                    if hasattr(self.main_window, 'right_sidebar') and self.main_window.right_sidebar.isVisible():
                        # Use metadata widget width (parent of info_edit) for text width
                        meta_w = info_edit.parent().width() if info_edit.parent() else self.main_window.right_sidebar.width()
                        if meta_w > 0:
                            doc = info_edit.document()
                            doc.setTextWidth(meta_w - 36)
                            info_edit.update()
                QTimer.singleShot(0, update_info_width)
        
        # Handle thumbnail mode - reflow thumbnails when any sidebar is resized
        if (index == 0 or index == 2) and self.main_window.current_view_mode == 'thumbnail':
            # Provide immediate visual feedback during dragging
            self._immediate_splitter_update()
            
            # Update MAX_THUMBNAIL_SIZE based on new container dimensions during splitter movement
            self.main_window.update_max_thumbnail_size()
            
            # Use a timer to debounce the final layout calculation
            # CRITICAL: Reuse existing timer instead of creating a new one to avoid GIL deadlock.
            if not hasattr(self.main_window, '_splitter_resize_timer'):
                # Initialize timer if it doesn't exist (shouldn't happen, but be safe)
                self.main_window._splitter_resize_timer = QTimer()
                self.main_window._splitter_resize_timer.setSingleShot(True)
                self.main_window._splitter_resize_timer.timeout.connect(self.main_window.update_layout_after_splitter_resize)
            
            self.main_window._splitter_resize_timer.stop()
            self.main_window._splitter_resize_timer.start(50)  # Reduced to 50ms for faster response
    
    def _immediate_splitter_update(self):
        """Provide immediate visual feedback during splitter dragging"""
        # Force layout propagation so viewport has correct size before we read it
        QApplication.processEvents()
        # Force immediate widget updates for visual feedback
        self.main_window.main_content_widget.updateGeometry()
        self.main_window.main_content_widget.update()
        
        # Recalculate thumbnail size for new viewport (prevents overflow when columns change)
        if self.main_window.current_view_mode == 'thumbnail' and self.main_window.displayed_images:
            self.main_window.set_dynamic_thumbnail_size()
        
        # Update canvas immediately if it exists to get new viewport width
        canvas = self.main_window.thumbnail_container.canvas
        # Clear any cached viewport width to force recalculation
        if hasattr(canvas, '_cached_viewport_width'):
            delattr(canvas, '_cached_viewport_width')
        if hasattr(canvas, '_cached_scrollbar_width'):
            delattr(canvas, '_cached_scrollbar_width')
        # Force immediate canvas update with new viewport width
        # Force the canvas to recalculate its viewport width
        canvas.get_viewport_width()  # This will update any cached values
        canvas.calculate_grid_layout()
        canvas.update()
        
        # Update browse view immediately if active
        if self.main_window.current_view_mode == 'browse' and hasattr(self.main_window, 'current_pixmap') and self.main_window.current_pixmap:
            # Quick update without full recalculation
            self.main_window.update_image_display()
        
        # Ensure current image stays on screen after layout recalc during splitter drag
        if self.main_window.current_view_mode == 'thumbnail' and self.main_window.displayed_images:
            QTimer.singleShot(50, self.main_window.ensure_highlighted_visible)
        
        # Force immediate repaint
        self.main_window.main_content_widget.repaint()
    
    def update_layout_after_splitter_resize(self):
        """Update thumbnail layout after splitter resize is complete"""
        # Force layout propagation so viewport reflects final splitter sizes
        QApplication.processEvents()
        # Force all widgets to update their sizes
        self.main_window.main_content_widget.updateGeometry()
        self.main_window.main_content_widget.update()
        
        # Skip thumbnail rebuild if we're in the middle of a fullscreen exit
        # The highlight should already be set correctly by the time this is called
        # CRITICAL: Reset the flag here to avoid needing another timer call (which causes GIL deadlock)
        if getattr(self.main_window, 'browse_view_exit_in_progress', False):
            self.main_window.browse_view_exit_in_progress = False
            return
        
        # Recalculate optimal thumbnail size for both canvas and non-canvas implementations
        if self.main_window.displayed_images:
            # Check if thumbnail size would actually change before recalculating
            # This avoids unnecessary refreshes when only sidebar visibility changes
            canvas = self.main_window.thumbnail_container.canvas
            if hasattr(canvas, '_cached_viewport_width'):
                delattr(canvas, '_cached_viewport_width')
            if hasattr(canvas, '_cached_scrollbar_width'):
                delattr(canvas, '_cached_scrollbar_width')
            
            # Calculate what the optimal size would be
            optimal_size = self.main_window.thumbnail_operations_manager.calculate_optimal_thumbnail_size()
            
            # Only call set_dynamic_thumbnail_size if size would actually change
            # Otherwise, just recalculate grid layout directly to avoid unnecessary refresh
            if optimal_size != self.main_window.current_thumbnail_size:
                self.main_window.set_dynamic_thumbnail_size()
            else:
                # Size hasn't changed, but viewport width might have - recalculate grid layout efficiently
                # Check if columns would actually change before recalculating
                old_columns = canvas.columns
                from thumbnails.thumbnail_constants import BASE_MARGIN, THUMBNAIL_SPACING, BORDER_SPACE
                viewport_width = canvas.get_viewport_width()
                available_width = viewport_width - (BASE_MARGIN * 2)
                if available_width > 0:
                    cell_width = canvas.thumbnail_size + BORDER_SPACE + THUMBNAIL_SPACING
                    new_columns = max(1, available_width // cell_width)
                    if new_columns != old_columns:
                        # Columns changed - need to recalculate grid
                        canvas.calculate_grid_layout()
                        canvas.update()
        
        # Update browse view if it's currently active
        if self.main_window.current_view_mode == 'browse' and hasattr(self.main_window, 'current_pixmap') and self.main_window.current_pixmap:
            mw = self.main_window
            old_w = mw.cached_container_width
            old_h = mw.cached_container_height
            if hasattr(mw, 'image_container'):
                mw.image_container.resize(mw.get_effective_display_size())
            mw._handle_browse_viewport_resize_after_container_change(old_w, old_h)
        
        # Ensure current image stays on screen after layout recalc (e.g. overlay 1→2 lines, sidebar resize)
        if self.main_window.current_view_mode == 'thumbnail' and self.main_window.displayed_images:
            QTimer.singleShot(50, self.main_window.ensure_highlighted_visible)
        
        # Force a complete repaint of the main content area
        self.main_window.main_content_widget.repaint()
        QApplication.processEvents()
    
    def update_max_thumbnail_size(self):
        """Update MAX_THUMBNAIL_SIZE based on container dimensions"""
        # Get the available size of the main content widget (stacks window)
        if hasattr(self.main_window, 'main_content_widget') and self.main_window.main_content_widget:
            import thumbnails.thumbnail_constants as thumbnail_constants
            width = self.main_window.main_content_widget.width()
            height = self.main_window.main_content_widget.height()
            
            # Calculate new max thumbnail size: min((min(width, height) * 0.80), max(width, height) / 3)
            new_max_size = round(max(width, height) / 2.2)
            # Update the global MAX_THUMBNAIL_SIZE in the module
            thumbnail_constants.MAX_THUMBNAIL_SIZE = int(new_max_size)
            
            # Also update the imported variable in this module
            global MAX_THUMBNAIL_SIZE
            MAX_THUMBNAIL_SIZE = int(new_max_size)
            
            # Update the imported variable in thumbnail_operations_manager if it exists
            try:
                import thumbnail_operations_manager
                thumbnail_operations_manager.MAX_THUMBNAIL_SIZE = int(new_max_size)
            except ImportError:
                pass
            
            # Update sidebar maximum width based on new thumbnail size
            if hasattr(self.main_window, 'combined_sidebar'):
                max_sidebar_width = self.main_window._calculate_max_sidebar_width()
                self.main_window.combined_sidebar.setMaximumWidth(max_sidebar_width)
            
            # Force thumbnail size recalculation to apply the new MAX_THUMBNAIL_SIZE
            if hasattr(self.main_window, 'displayed_images') and self.main_window.displayed_images:
                QTimer.singleShot(10, self.main_window.set_dynamic_thumbnail_size)
    
    def set_splitter_sizes_safe(self, sizes):
        """Set splitter sizes while suppressing splitterMoved signals to prevent Qt from overriding saved width."""
        mw = self.main_window
        mw._suppress_splitter_moved = True
        try:
            mw.main_splitter.setSizes(sizes)
        finally:
            QTimer.singleShot(10, lambda: setattr(mw, '_suppress_splitter_moved', False))

    def force_resize_event(self):
        """Force a resize event to trigger layout updates"""
        # Create a fake resize event to trigger the resizeEvent handler
        current_size = self.main_window.size()
        fake_event = QResizeEvent(current_size, current_size)
        self.main_window.resizeEvent(fake_event)
    
    def _calculate_max_sidebar_width(self):
        """Calculate the maximum sidebar width to allow one column of thumbnails, accounting for right sidebar"""
        if not hasattr(self.main_window, 'current_thumbnail_size') or not hasattr(self.main_window, 'thumbnail_container'):
            return self.main_window.width() - 200  # Fallback if not initialized
        
        # Calculate width needed for one column of thumbnails
        border_space = 4  # Border space for highlighting
        one_column_width = (self.main_window.current_thumbnail_size + 
                           border_space + 
                           self.main_window.thumbnail_container.HORIZONTAL_SPACING)
        
        # Account for right sidebar if visible
        right_sidebar_width = 0
        if hasattr(self.main_window, 'right_sidebar') and self.main_window.right_sidebar.isVisible():
            right_sidebar_width = self.main_window.right_sidebar.width()
        elif hasattr(self.main_window, 'right_sidebar_width') and self.main_window.right_sidebar_visible:
            right_sidebar_width = self.main_window.right_sidebar_width
        
        # Maximum sidebar width is window width minus one column width and right sidebar
        max_width = self.main_window.width() - one_column_width - right_sidebar_width - 40 # 40px is a fudge factor to ensure the sidebar is not too wide
        
        # Ensure minimum width for usability
        return max(max_width, 200)
    

    def _get_thumbnail_cell_width(self):
        """Get current thumbnail cell width including borders and spacing"""
        try:
            from thumbnails.thumbnail_constants import BORDER_SPACE, THUMBNAIL_SPACING
            
            # Get current thumbnail size from canvas or main window
            thumbnail_size = 0
            if hasattr(self.main_window, 'thumbnail_container') and hasattr(self.main_window.thumbnail_container, 'canvas'):
                canvas = self.main_window.thumbnail_container.canvas
                if hasattr(canvas, 'thumbnail_size'):
                    thumbnail_size = canvas.thumbnail_size
            elif hasattr(self.main_window, 'current_thumbnail_size'):
                thumbnail_size = self.main_window.current_thumbnail_size
            
            if thumbnail_size > 0:
                # Cell width = thumbnail_size + border_space + spacing
                return thumbnail_size + BORDER_SPACE + THUMBNAIL_SPACING
            
            # Fallback: use a reasonable default
            return 200  # Approximate cell width for medium thumbnails
        except Exception:
            return 200  # Fallback on error
    
    def _on_sidebar_resized(self):
        """Handle sidebar resize events - debounced to avoid excessive recalculations"""
        # Get current sidebar width
        if hasattr(self.main_window, 'combined_sidebar'):
            current_width = self.main_window.combined_sidebar.width()
        else:
            current_width = getattr(self.main_window, 'sidebar_width', 0)
        
        # Get current thumbnail cell width (including borders and spacing)
        cell_width = self._get_thumbnail_cell_width()
        
        # Check if change since last refresh exceeds thumbnail cell width
        if self._last_sidebar_width is not None and cell_width > 0:
            width_change = abs(current_width - self._last_sidebar_width)
            if width_change >= cell_width:
                # Significant change - force immediate recalculation
                self._sidebar_resize_timer.stop()
                self._on_sidebar_resize_debounced()
                return
        
        # Small change - use debounce timer
        self._sidebar_resize_timer.stop()
        self._sidebar_resize_timer.start(150)  # 150ms debounce delay
    
    def _on_sidebar_resize_debounced(self):
        """Handle debounced sidebar resize events"""
        # Update canvas layout when sidebar is resized
        self.main_window.update_max_thumbnail_size()
        
        # Update tracked sidebar width after recalculation
        if hasattr(self.main_window, 'combined_sidebar'):
            self._last_sidebar_width = self.main_window.combined_sidebar.width()
        else:
            self._last_sidebar_width = getattr(self.main_window, 'sidebar_width', 0)
        
        # Handle browse mode - resize image container when combined sidebar is resized
        # Delay to allow Qt to finish updating the layout before recalculating fit-to-screen
        if self.main_window.current_view_mode == 'browse':
            QTimer.singleShot(100, self.main_window._resize_browse_view_image_container)
        
        # Handle list view mode - update row rectangles and header when sidebar is resized
        if self.main_window.current_view_mode == 'list':
            if hasattr(self.main_window, 'list_view_container') and self.main_window.list_view_container:
                QTimer.singleShot(100, self.main_window.list_view_container._handle_viewport_resize)
    
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
    
    def get_physical_screen_size(self):
        """Get the physical screen size"""
        return self.main_window.screen().size()
    
    def get_effective_display_size(self):
        """Get the effective display size accounting for window decorations"""
        return self.main_window.main_content_widget.size()
    
    def get_scrollbar_width(self):
        """Get the width of the scrollbar"""
        if hasattr(self.main_window, 'scroll_area') and self.main_window.scroll_area:
            scrollbar = self.main_window.scroll_area.verticalScrollBar()
            if scrollbar.isVisible():
                return scrollbar.width()
        return 0
    
    def get_actual_grid_info(self):
        """Get actual grid information from canvas"""
        if hasattr(self.main_window, 'thumbnail_container') and self.main_window.thumbnail_container:
            canvas = self.main_window.thumbnail_container.canvas
            if hasattr(canvas, 'get_grid_info'):
                return canvas.get_grid_info()
        return None
    
    def calculate_page_scroll_info(self):
        """Calculate page scroll information"""
        if hasattr(self.main_window, 'thumbnail_container') and self.main_window.thumbnail_container:
            canvas = self.main_window.thumbnail_container.canvas
            if hasattr(canvas, 'calculate_page_scroll_info'):
                return canvas.calculate_page_scroll_info()
        return None
