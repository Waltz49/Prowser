#!/usr/bin/env python3
"""
Sidebar Manager
Handles sidebar components (tree, preview) visibility and management
"""

import os
from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import QApplication


class SidebarManager:
    """Manages sidebar components (tree, preview, rename status)"""
    
    def __init__(self, main_window):
        """
        Initialize the sidebar manager
        
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
        """Handle VIEW_MODE_CHANGED - sidebar state may need refresh (manage_sidebar_visibility called by view switch)"""
        pass  # manage_sidebar_visibility_for_view_mode is called by view switch code
    
    def toggle_file_tree(self):
        """Toggle the visibility of the file tree and resize canvas accordingly"""
        if hasattr(self.main_window, 'combined_sidebar'):
            self.main_window.combined_sidebar.set_tree_visible(not self.main_window.combined_sidebar.is_tree_visible())
            return self.main_window.combined_sidebar.is_tree_visible()
        else:
            return self.main_window.view_manager.toggle_file_tree()
    
    def toggle_preview(self):
        """Toggle the visibility of the preview widget and resize canvas accordingly"""
        if hasattr(self.main_window, 'combined_sidebar'):
            self.main_window.combined_sidebar.set_preview_visible(not self.main_window.combined_sidebar.is_preview_visible())
            return self.main_window.combined_sidebar.is_preview_visible()
        else:
            # Fallback to old behavior if combined sidebar not available
            if not hasattr(self.main_window, 'preview_widget'):
                return False
            
            # Hide tree if it's visible (they can't both be shown at the same time)
            if self.main_window.tree_container.isVisible():
                self.main_window.tree_container.hide()
                self.main_window.file_tree_visible = False
                if hasattr(self.main_window, 'toggle_file_tree_action'):
                    self.main_window.toggle_file_tree_action.setChecked(False)
                    self.main_window.toggle_file_tree_action.setText('Show File Tree')
                
                # Handle browse mode - resize image container when tree view is hidden
                if self.main_window.current_view_mode == 'browse':
                    if hasattr(self.main_window, 'image_container'):
                        available_size = self.main_window.get_effective_display_size()
                        self.main_window.image_container.resize(available_size)
            
            # Toggle preview visibility
            if self.main_window.preview_widget.isVisible():
                self.main_window.preview_widget.hide()
                self.main_window.preview_visible = False
            else:
                self.main_window.preview_widget.show()
                self.main_window.preview_visible = True
                self.main_window.preview_widget.update_preview()
            
            # Update menu action
            if hasattr(self.main_window, 'toggle_preview_action'):
                self.main_window.toggle_preview_action.setChecked(self.main_window.preview_visible)
                self.main_window.toggle_preview_action.setText('Hide Preview' if self.main_window.preview_visible else 'Show Preview')
            
            # Save settings
            self.main_window.config.update_setting('preview_visible', self.main_window.preview_visible)
            
            return self.main_window.preview_visible
    
    def toggle_preview_fit_mode(self):
        """Toggle preview fit mode"""
        if hasattr(self.main_window, 'preview_widget'):
            self.main_window.preview_widget.toggle_fit_mode()
    
    def update_preview_if_visible(self):
        """Update preview widget if it's visible"""
        if hasattr(self.main_window, 'preview_widget') and self.main_window.preview_widget.isVisible():
            self.main_window.preview_widget.update_preview()
    
    def ensure_tree_initialized(self):
        """Ensure the file tree is initialized"""
        if hasattr(self.main_window, 'file_tree_handler') and self.main_window.file_tree_handler:
            self.main_window.file_tree_handler.ensure_tree_initialized()
    
    def _synchronize_tree_with_current_state(self):
        """Synchronize tree view with current state"""
        if hasattr(self.main_window, 'file_tree_handler') and self.main_window.file_tree_handler:
            if self.main_window.file_tree_handler.is_tree_initialized():
                self.main_window.file_tree_handler.highlight_current_directory()
                self.main_window.file_tree_handler.highlight_current_file()
    
    def focus_tree(self):
        """Focus the file tree"""
        if hasattr(self.main_window, 'tree_container'):
            self.main_window.tree_container.setFocus()
    
    def focus_canvas(self):
        """Focus the canvas"""
        if hasattr(self.main_window, 'thumbnail_container'):
            self.main_window.thumbnail_container.setFocus()
    
    def _set_initial_focus(self):
        """Set initial focus"""
        self.focus_canvas()
    
    def setup_file_tree_callbacks(self):
        """Setup callbacks for file tree interactions"""
        if hasattr(self.main_window, 'file_tree_handler') and self.main_window.file_tree_handler:
            self.main_window.file_tree_handler.setup_callbacks()
    
    def on_directory_selected(self, directory_path: str):
        """Handle directory selection from tree"""
        self.main_window.open_directory(directory_path)
    
    def on_file_selected(self, file_path: str):
        """Handle file selection from tree"""
        self.main_window.open_specific_file(file_path)
    
    def on_file_double_clicked(self, file_path: str):
        """Handle file double-click from tree"""
        self.main_window.open_specific_file(file_path)
    
    def toggle_rename_status(self):
        """Toggle rename status checking"""
        if not hasattr(self.main_window, 'rename_status_manager'):
            return
        
        enabled = self.main_window.rename_status_manager.is_enabled()
        new_enabled = not enabled
        
        self.main_window.rename_status_manager.set_enabled(new_enabled)
        
        # Update menu checkmark
        if hasattr(self.main_window, 'show_rename_status_action'):
            self.main_window.show_rename_status_action.setChecked(new_enabled)
        
        # Update button icon in file tree
        if hasattr(self.main_window, 'file_tree_handler') and self.main_window.file_tree_handler:
            if hasattr(self.main_window.file_tree_handler, 'update_rename_status_button_icon'):
                self.main_window.file_tree_handler.update_rename_status_button_icon()
        
        if new_enabled:
            # Load existing status from file
            self.main_window.rename_status_manager.load_all_status()
            # Perform full scan of all relevant dirs when turned on - use timer to ensure tree is ready
            from PySide6.QtCore import QTimer
            QTimer.singleShot(100, lambda: self.update_rename_status(full_scan=True))
        else:
            # Clear status and refresh tree to remove checkmarks
            if hasattr(self.main_window, 'file_tree_handler') and self.main_window.file_tree_handler:
                if self.main_window.file_tree_handler.is_tree_initialized():
                    self.main_window.file_tree_handler.rebuild_tree()
    
    def update_rename_status_for_directory(self, directory: str):
        """Update rename status for a specific directory and refresh its checkmark without rebuilding tree."""
        if not hasattr(self.main_window, 'rename_status_manager'):
            return
        if not self.main_window.rename_status_manager.is_enabled():
            return
        
        # Get config values - use same keys as rename operations (rename_custom_prefix, rename_increment_length)
        config = self.main_window.config.load_settings()
        rename_prefix_template = config.get('rename_custom_prefix', 'image-%d')
        increment_length = config.get('rename_increment_length', 5)
        max_depth = config.get('rename_status_max_depth', 3)
        filter_pattern = self.main_window.filter_pattern or ''
        
        # Get image extensions
        from thumbnail_constants import get_image_extensions
        extensions = get_image_extensions()
        
        # Update status for this directory and its immediate children
        self.main_window.rename_status_manager.update_status_for_directory_tree(
            root_directory=directory,
            max_depth=max_depth,
            rename_prefix_template=rename_prefix_template,
            increment_length=increment_length,
            filter_pattern=filter_pattern,
            extensions=extensions,
            visible_directories=[directory]
        )
        
        # Refresh tree view to show updated checkmark
        if hasattr(self.main_window, 'file_tree_handler') and self.main_window.file_tree_handler:
            if self.main_window.file_tree_handler.is_tree_initialized():
                from PySide6.QtCore import Qt
                filter_proxy = self.main_window.file_tree_handler.filter_proxy
                file_model = self.main_window.file_tree_handler.file_model
                
                if filter_proxy and file_model:
                    try:
                        # Get source index from file model
                        index = file_model.index(directory)
                        if index.isValid():
                            # Map to proxy index
                            proxy_index = filter_proxy.mapFromSource(index)
                            if proxy_index.isValid():
                                # Emit dataChanged with DecorationRole to trigger icon redraw
                                filter_proxy.dataChanged.emit(
                                    proxy_index, proxy_index, [Qt.DecorationRole]
                                )
                    except Exception:
                        # Fallback: refresh entire tree view
                        if hasattr(self.main_window.file_tree_handler, 'file_tree'):
                            self.main_window.file_tree_handler.file_tree.viewport().update()
    
    def update_rename_status(self, full_scan=False):
        """Update rename status for directories in tree.
        
        When full_scan=True: scan all relevant dirs from enabled root directories (used when
        toggle is turned on, after mass rename, or on cmd-R). Otherwise scan visible (expanded) dirs.
        """
        if not hasattr(self.main_window, 'rename_status_manager'):
            return
        if not self.main_window.rename_status_manager.is_enabled():
            return

        # Get config values - use same keys as rename operations (rename_custom_prefix, rename_increment_length)
        config = self.main_window.config.load_settings()
        rename_prefix_template = config.get('rename_custom_prefix', 'image-%d')
        increment_length = config.get('rename_increment_length', 5)
        max_depth = config.get('rename_status_max_depth', 3)
        filter_pattern = self.main_window.filter_pattern or ''
        
        # Get image extensions
        from thumbnail_constants import get_image_extensions
        extensions = get_image_extensions()

        if full_scan:
            # Full scan: scan all enabled root directories recursively (all relevant dirs)
            from file_tree_handler import get_enabled_root_directories
            root_directories = [d for d in get_enabled_root_directories() if d and os.path.isdir(d)]
            if not root_directories and hasattr(self.main_window, 'current_directory') and self.main_window.current_directory:
                root_directories = [self.main_window.current_directory]
            if not root_directories:
                return
            status_map = {}
            for root_directory in root_directories:
                scan_result = self.main_window.rename_status_manager.scan_directory_tree(
                    root_directory=root_directory,
                    max_depth=max_depth,
                    rename_prefix_template=rename_prefix_template,
                    increment_length=increment_length,
                    filter_pattern=filter_pattern,
                    extensions=extensions,
                    visible_directories=None  # Full recursive scan
                )
                status_map.update(scan_result)
            for root_directory in root_directories:
                self.main_window.rename_status_manager.update_status_for_directory_tree(
                    root_directory=root_directory,
                    max_depth=max_depth,
                    rename_prefix_template=rename_prefix_template,
                    increment_length=increment_length,
                    filter_pattern=filter_pattern,
                    extensions=extensions,
                    visible_directories=None
                )
        else:
            # Normal scan: visible (expanded) directories only
            visible_directories = []
            if hasattr(self.main_window, 'file_tree_handler') and self.main_window.file_tree_handler:
                if self.main_window.file_tree_handler.is_tree_initialized():
                    visible_directories = self.main_window.file_tree_handler.get_expanded_directories()
            
            if not visible_directories and hasattr(self.main_window, 'current_directory') and self.main_window.current_directory:
                visible_directories = [self.main_window.current_directory]
            
            if not visible_directories and (hasattr(self.main_window, 'file_tree_handler') and self.main_window.file_tree_handler and self.main_window.file_tree_handler.is_tree_initialized()):
                if hasattr(self.main_window.file_tree_handler, 'file_model'):
                    root_path = self.main_window.file_tree_handler.file_model.rootPath()
                    if root_path and root_path != '/':
                        visible_directories = [root_path]
                    elif hasattr(self.main_window, 'current_directory') and self.main_window.current_directory:
                        visible_directories = [self.main_window.current_directory]
            
            if not visible_directories:
                return

            root_directory = self.main_window.current_directory if hasattr(self.main_window, 'current_directory') and self.main_window.current_directory else visible_directories[0]
            
            status_map = self.main_window.rename_status_manager.scan_directory_tree(
                root_directory=root_directory,
                max_depth=max_depth,
                rename_prefix_template=rename_prefix_template,
                increment_length=increment_length,
                filter_pattern=filter_pattern,
                extensions=extensions,
                visible_directories=visible_directories
            )
            
            self.main_window.rename_status_manager.update_status_for_directory_tree(
                root_directory=root_directory,
                max_depth=max_depth,
                rename_prefix_template=rename_prefix_template,
                increment_length=increment_length,
                filter_pattern=filter_pattern,
                extensions=extensions,
                visible_directories=visible_directories
            )
        
        # Refresh tree view to show updated checkmarks
        # Emit dataChanged for each VISIBLE directory (scanned dirs may be filtered out of tree)
        if hasattr(self.main_window, 'file_tree_handler') and self.main_window.file_tree_handler:
            if self.main_window.file_tree_handler.is_tree_initialized():
                from PySide6.QtCore import Qt
                handler = self.main_window.file_tree_handler
                if hasattr(handler, 'get_all_visible_directory_proxy_indices'):
                    for proxy_index in handler.get_all_visible_directory_proxy_indices():
                        try:
                            handler.filter_proxy.dataChanged.emit(
                                proxy_index, proxy_index, [Qt.DecorationRole]
                            )
                        except Exception:
                            continue
                if hasattr(handler, 'file_tree'):
                    handler.file_tree.viewport().update()
    
    def manage_sidebar_visibility_for_view_mode(self, view_mode):
        """Manage sidebar visibility based on view mode"""
        if view_mode == 'browse':
            # Hide sidebar in browse mode
            if hasattr(self.main_window, 'combined_sidebar'):
                self.main_window.combined_sidebar.hide()
                QApplication.processEvents()
        elif view_mode == 'thumbnail':
            # Show sidebar in thumbnail mode if it was visible before
            if hasattr(self.main_window, 'combined_sidebar'):
                if self.main_window.file_tree_visible or self.main_window.preview_visible:
                    self.main_window.combined_sidebar.show()
                    QApplication.processEvents()
    
    def update_sidebar_menu_actions_for_view_mode(self, view_mode):
        """Update sidebar menu actions based on view mode"""
        if hasattr(self.main_window, 'menu_manager') and self.main_window.menu_manager:
            self.main_window.menu_manager.update_sidebar_menu_actions_for_view_mode(view_mode)
    

    def _get_thumbnail_cell_width(self):
        """Get current thumbnail cell width including borders and spacing"""
        try:
            from thumbnail_constants import BORDER_SPACE, THUMBNAIL_SPACING
            
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
