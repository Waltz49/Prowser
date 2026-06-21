#!/usr/bin/env python3
"""
Thumbnail Display Manager
Handles thumbnail generation, display, and management
"""

from PySide6.QtCore import QTimer
from event_bus import DISPLAYED_IMAGES_CHANGED


class ThumbnailDisplayManager:
    """Manages thumbnail display and generation operations"""
    
    def __init__(self, main_window):
        """
        Initialize the thumbnail display manager
        
        Args:
            main_window: Reference to the main ImageBrowserWindow instance
        """
        self.main_window = main_window
        # Subscribe to displayed images changes via event bus
        if hasattr(main_window, 'event_bus') and main_window.event_bus:
            main_window.event_bus.subscribe(DISPLAYED_IMAGES_CHANGED, self._on_displayed_images_changed)

    def _on_displayed_images_changed(self, images: list):
        """Handle DISPLAYED_IMAGES_CHANGED event - update thumbnail canvas"""
        self.generate_thumbnails(force_refresh=False)
    
    def generate_thumbnails(self, force_refresh=False):
        """Create responsive thumbnail grid with canvas-based display"""
        # Check if we have images to process
        if not self.main_window.displayed_images:
            # Only check for last known directory if current_directory is not set
            # This prevents overriding an explicitly opened empty directory
            if not self.main_window.current_directory:
                if hasattr(self.main_window, 'directory_loader'):
                    self.main_window.directory_loader._check_and_open_last_known_directory()
            # Always update the thumbnail canvas to show empty state
            self.main_window.thumbnail_container.canvas.check_and_show_empty_directory_message(self.main_window.displayed_images)
            # Set thumbnails to empty list to clear the canvas
            self.main_window.thumbnail_container.set_thumbnails([], self.main_window.current_thumbnail_size)
            return
        
        # Use displayed_images directly
        images_to_process = self.main_window.displayed_images
        
        # Calculate grid based on the actual number of images being processed
        num_images_to_process = len(images_to_process)
        
        # Only recalculate grid size if not manually set
        if not self.main_window.manual_thumbnail_size:
            if (
                getattr(self.main_window, 'reference_graph_active', False)
                and getattr(self.main_window, 'reference_graph_data', None)
            ):
                from search.reference_graph_layout import compute_reference_graph_dynamic_thumbnail_size

                display_size = self.main_window.get_effective_display_size()
                overlay = self.main_window.thumbnail_operations_manager._get_overlay_height_for_calculation()
                self.main_window.current_thumbnail_size = compute_reference_graph_dynamic_thumbnail_size(
                    self.main_window.reference_graph_data,
                    display_size.width(),
                    display_size.height(),
                    overlay,
                )
            else:
                self.main_window.current_thumbnail_size, _, _ = (
                    self.main_window.thumbnail_operations_manager.calculate_grid_for_images(
                        num_images_to_process
                    )
                )
        else:
            # Use current size and calculate grid dimensions
            pass
        
        # Check if we already have thumbnails and can preserve them
        # Use reorder_thumbnails to preserve loaded pixmaps when possible
        # BUT: if force_refresh is True, always do a full rebuild to ensure thumbnails are reloaded
        if  (self.main_window.thumbnail_container.canvas.thumbnails and 
            len(self.main_window.thumbnail_container.canvas.thumbnails) > 0 and
            not force_refresh):  # Skip optimization if force_refresh is True
            # Check if the image list is the same (just reordering) or if we can preserve most thumbnails
            current_paths = [thumb.image_path for thumb in self.main_window.thumbnail_container.canvas.thumbnails]
            
            # If the image lists are the same, just reorder
            if current_paths == images_to_process:
                # Update thumbnail size in canvas if needed
                self.main_window.thumbnail_container.canvas.thumbnail_size = self.main_window.current_thumbnail_size
                # Reorder thumbnails which will recalculate grid layout
                self.main_window.thumbnail_container.canvas.reorder_thumbnails(images_to_process, force_recalculate_grid=True)
                
                # Set initial highlight - preserve existing highlight_index if it's valid
                if images_to_process:
                    if not (0 <= self.main_window.highlight_index < len(images_to_process)):
                        self.main_window.highlight_index = 0
                    self.main_window.thumbnail_container.set_highlighted_index(self.main_window.highlight_index)

                    self.main_window.highlight_image()
                return
            
            # Only do full rebuild if we have a resize in progress or if images are very different
            if not getattr(self.main_window, '_resize_in_progress', False):
                # Update thumbnail size in canvas if needed
                self.main_window.thumbnail_container.canvas.thumbnail_size = self.main_window.current_thumbnail_size
                
                # Reorder thumbnails which will recalculate grid layout
                self.main_window.thumbnail_container.canvas.reorder_thumbnails(images_to_process, force_recalculate_grid=True)
                
                # Set initial highlight - preserve existing highlight_index if it's valid
                if images_to_process:
                    if not (0 <= self.main_window.highlight_index < len(images_to_process)):
                        self.main_window.highlight_index = 0
                    self.main_window.thumbnail_container.set_highlighted_index(self.main_window.highlight_index)
                
                # CRITICAL: Restore visual selections from selected_files (source of truth)
                # This ensures selections persist through reorder operations
                # BUT: Skip if we're in the middle of a rename operation (selections should be cleared)
                # update_canvas_selection() derives selected_indices from selected_files (the source of truth)
                if not getattr(self.main_window, '_skip_selection_restore_during_refresh', False):
                    if hasattr(self.main_window, '_emit_selection_changed'):
                        self.main_window._emit_selection_changed()
                
                # Start background loading for any new thumbnails that were created by reorder_thumbnails
                self.main_window.start_background_thumbnail_loading_if_needed()
                
                return
                
        # Full rebuild path - clear everything and start fresh
        # CRITICAL: If force_refresh is True, invalidate thumbnails to mark them for reload
        # But don't clear cache - let cache manager handle stale cache detection via mtime
        # This is much more performant than clearing cache for thousands of files
        if force_refresh:
            # Invalidate all existing thumbnails to clear pixmaps and mark as loading
            # This forces them to reload, but cache manager will check mtime and reload if needed
            if self.main_window.thumbnail_container.canvas.thumbnails:
                self.main_window.thumbnail_container.canvas.invalidate_thumbnails()
        
        self.main_window.clear_thumbnails()
        
        # Set thumbnails on the canvas
        self.main_window.thumbnail_container.set_thumbnails(images_to_process, self.main_window.current_thumbnail_size)

        # set_thumbnails only builds ThumbnailItems + grid; it does not create EXIF/duplicate section
        # separators. reorder_thumbnails applies section metadata to the layout (same as MD5 duplicates).
        if images_to_process:
            canvas = self.main_window.thumbnail_container.canvas
            sm = getattr(self.main_window, "current_sort_mode", None)
            if sm is not None and hasattr(sm, "value"):
                v = sm.value
                if v == "duplicates" and getattr(self.main_window, "duplicate_sections", None):
                    canvas.reorder_thumbnails(images_to_process, force_recalculate_grid=True)
                elif v in ("exif_date", "exif_year") and getattr(
                    self.main_window, "exif_date_sections", None
                ):
                    canvas.reorder_thumbnails(images_to_process, force_recalculate_grid=True)
                elif getattr(self.main_window, "reference_graph_active", False):
                    canvas.reorder_thumbnails(images_to_process, force_recalculate_grid=True)

        # Set initial highlight - preserve existing highlight_index if it's valid
        if images_to_process:
            if not (0 <= self.main_window.highlight_index < len(images_to_process)):
                self.main_window.highlight_index = 0
            self.main_window.thumbnail_container.set_highlighted_index(self.main_window.highlight_index)
        
        # CRITICAL: Restore visual selections from selected_files (source of truth)
        # This ensures selections persist through refresh operations
        # BUT: Skip if we're in the middle of a rename operation (selections should be cleared)
        if not getattr(self.main_window, '_skip_selection_restore_during_refresh', False):
            if hasattr(self.main_window, '_emit_selection_changed'):
                self.main_window._emit_selection_changed()
        
        # Ensure cache manager signals are connected to canvas
        if hasattr(self.main_window.thumbnail_container, 'connect_cache_manager_signals'):
            self.main_window.thumbnail_container.connect_cache_manager_signals()
        
        # Update list view if in list mode
        if hasattr(self.main_window, 'current_view_mode') and self.main_window.current_view_mode == 'list':
            if hasattr(self.main_window, 'view_manager'):
                self.main_window.view_manager.update_list_view()
        
        # Start loading thumbnails in the background
        self.main_window.start_background_thumbnail_loading_if_needed()
    
    def _start_throttled_thumbnail_loading(self, images_to_process):
        """Start loading thumbnails using background worker to avoid blocking UI"""
        if not images_to_process:
            return
        
        # Import here to avoid circular import (image_browser_window imports this module)
        from workers.window_background_workers import ThumbnailLoadingWorker
        
        # Cancel any existing worker FIRST, before creating a new one
        # Store reference to old worker to avoid race conditions with delayed cleanup
        old_worker = None
        if hasattr(self.main_window, 'thumbnail_worker') and self.main_window.thumbnail_worker:
            try:
                if self.main_window.thumbnail_worker.isRunning():
                    self.main_window.thumbnail_worker.cancel()
                    # Store reference for delayed cleanup
                    old_worker = self.main_window.thumbnail_worker
                    # Clear reference immediately so new worker can be created
                    self.main_window.thumbnail_worker = None
                else:
                    # Worker not running, just clear reference
                    old_worker = self.main_window.thumbnail_worker
                    self.main_window.thumbnail_worker = None
            except Exception:
                # If anything goes wrong, clear reference and continue
                try:
                    old_worker = self.main_window.thumbnail_worker
                except:
                    pass
                self.main_window.thumbnail_worker = None
        
        # Schedule cleanup of old worker (if any) after a delay
        # This prevents blocking but doesn't interfere with new worker creation
        if old_worker:
            def cleanup_old_worker():
                try:
                    # Wait for old worker to finish (with timeout to avoid blocking)
                    if old_worker and old_worker.isRunning():
                        old_worker.wait(100)  # Wait up to 100ms for graceful shutdown
                except Exception:
                    pass
            QTimer.singleShot(100, cleanup_old_worker)
        
        # Create and start the background worker IMMEDIATELY
        # Don't wait for cleanup - start loading thumbnails right away
        self.main_window.thumbnail_worker = ThumbnailLoadingWorker(
            self.main_window.cache_manager, 
            images_to_process, 
            self.main_window.current_thumbnail_size, 
            self.main_window
        )
        
        # Connect signals
        self.main_window.thumbnail_worker.thumbnail_loaded.connect(self.main_window._on_thumbnail_loaded_from_worker)
        self.main_window.thumbnail_worker.finished.connect(self.main_window._on_thumbnail_worker_finished)
        self.main_window.thumbnail_worker.error.connect(self.main_window._on_thumbnail_worker_error)
        self.main_window.thumbnail_worker.progress_updated.connect(self.main_window._on_thumbnail_progress_updated)
        
        # Start immediately - don't wait for cleanup
        self.main_window.thumbnail_worker.start()
    
    def populate_indices_arrays(self):
        """Populate the image indices arrays for navigation"""
        if self.main_window.displayed_images:
            image_count = len(self.main_window.displayed_images)
        else:
            self.main_window.image_indices = []
            self.main_window.image_indices_sequential = []
            self.main_window.image_indices_random = []
            return
        
        import random
        from sort_mode import SortMode
        
        self.main_window.image_indices_sequential = list(range(image_count))
        self.main_window.image_indices_random = self.main_window.image_indices_sequential.copy()
        random.shuffle(self.main_window.image_indices_random)
        
        # Set image_indices based on current browsing mode
        # Preserve the current random mode state
        if self.main_window.current_sort_mode == SortMode.RANDOM:
            # If we're in random mode, use random indices
            self.main_window.image_indices = self.main_window.image_indices_random.copy()
        else:
            # If we're in sequential mode (date or name sorted), use sequential indices
            self.main_window.image_indices = self.main_window.image_indices_sequential.copy()
        
        # DO NOT modify highlight_index here - it's derived from current_image_path
        # Callers must call _sync_highlight_index_from_current_image_path() after this
    
    def clear_thumbnails(self):
        """Clear all thumbnails from the canvas"""
        if hasattr(self.main_window, 'thumbnail_container') and self.main_window.thumbnail_container:
            self.main_window.thumbnail_container.set_thumbnails([], self.main_window.current_thumbnail_size)
    
    def _find_next_image_after_deletion(self, original_displayed, files_to_remove, active_file_path=None):
        """Find the next non-deleted image to highlight after deletion."""
        mw = self.main_window
        if not files_to_remove or not original_displayed:
            if mw.highlight_index >= len(mw.displayed_images):
                mw.highlight_index = max(0, len(mw.displayed_images) - 1)
            return
        if active_file_path is None:
            active_file_path = mw.get_current_image_path()
        active_file_is_being_removed = active_file_path and active_file_path in files_to_remove
        active_file_position = None
        if active_file_path and active_file_path in original_displayed:
            active_file_position = original_displayed.index(active_file_path)
        if active_file_position is not None and not active_file_is_being_removed:
            if active_file_path in mw.displayed_images:
                mw.set_current_image_by_path(active_file_path)
                return
        if active_file_position is None:
            selected_files = mw.selection_manager.get_selected_files()
            if selected_files:
                last_selected = selected_files[-1]
                if last_selected in original_displayed:
                    active_file_position = original_displayed.index(last_selected)
                    active_file_path = last_selected
        if active_file_position is None:
            last_deleted_position = None
            for file_path in files_to_remove:
                if file_path in original_displayed:
                    position = original_displayed.index(file_path)
                    if last_deleted_position is None or position > last_deleted_position:
                        last_deleted_position = position
            if last_deleted_position is not None:
                active_file_position = last_deleted_position
        if active_file_position is None:
            mw._sync_highlight_index_from_current_image_path()
            return
        next_image_path = None
        for i in range(active_file_position + 1, len(original_displayed)):
            if original_displayed[i] not in files_to_remove:
                next_image_path = original_displayed[i]
                break
        if next_image_path is None:
            for i in range(active_file_position - 1, -1, -1):
                if original_displayed[i] not in files_to_remove:
                    next_image_path = original_displayed[i]
                    break
        if next_image_path and next_image_path in mw.displayed_images:
            mw.set_current_image_by_path(next_image_path)
        elif mw.displayed_images:
            mw.set_current_image_by_path(None, fallback_index=0)

    def remove_thumbnails_for_files(self, files_to_remove, active_file_path=None):
        """Remove specific thumbnails for deleted files without rebuilding the entire grid.
        In formatted list mode (EXIF date/duplicate finder), keeps slots and draws red X overlay instead."""
        if not files_to_remove:
            return

        model = getattr(self.main_window, 'file_data_model', None)
        if not model:
            return
        current_images = list(model.get_displayed_images())
        # Store original displayed_images for finding next image logic
        original_displayed = current_images.copy()

        # Capture active file path before removal if not provided
        if active_file_path is None:
            active_file_path = self.main_window.get_current_image_path()

        is_formatted = getattr(self.main_window, '_is_formatted_list_mode', lambda: False)()
        if is_formatted:
            # Formatted list: keep slots, add to placeholders, draw red X overlay
            placeholders = getattr(self.main_window, 'deleted_file_placeholders', None)
            if placeholders is not None:
                for file_path in files_to_remove:
                    if file_path in current_images:
                        placeholders.add(file_path)
        else:
            # Normal mode: remove from displayed_images
            for file_path in files_to_remove:
                if file_path in current_images:
                    current_images.remove(file_path)
            model.set_displayed_images(current_images)

        # Update indices arrays (only needed when we actually removed from list)
        if not is_formatted:
            self.populate_indices_arrays()

        # Find the next non-deleted image to highlight using file path (source of truth)
        self._find_next_image_after_deletion(original_displayed, files_to_remove, active_file_path)

        # CRITICAL: Ensure highlight_index is synced from current_image_path after deletion
        self.main_window._sync_highlight_index_from_current_image_path()

        # Update view based on current mode
        if hasattr(self.main_window, 'current_view_mode') and self.main_window.current_view_mode == 'list':
            if hasattr(self.main_window, 'view_manager') and self.main_window.view_manager:
                self.main_window.view_manager.update_list_view()
        else:
            if is_formatted:
                # Formatted mode: trigger repaint to show red X overlays (list unchanged)
                if hasattr(self.main_window, 'thumbnail_container') and self.main_window.thumbnail_container:
                    self.main_window.thumbnail_container.canvas.update()
            else:
                self.main_window.thumbnail_container.canvas.reorder_thumbnails(self.main_window.displayed_images, force_recalculate_grid=False)

        # Highlight the next image
        self.main_window.highlight_image()

        # Check if we need to trigger auto-open when list becomes empty
        if not self.main_window.displayed_images:
            self.generate_thumbnails()

        return
    
    def add_thumbnails_for_files(self, files_to_add, positions=None):
        """Add thumbnails for restored files without rebuilding the entire grid"""
        if not files_to_add:
            return

        # Remove from deleted placeholders (restored files no longer show red X)
        if hasattr(self.main_window, 'clear_deleted_placeholders_for_paths'):
            self.main_window.clear_deleted_placeholders_for_paths(files_to_add)

        # Add files to displayed_images list at correct positions (via model)
        model = getattr(self.main_window, 'file_data_model', None)
        if not model:
            return
        current_images = list(model.get_displayed_images())
        if positions and len(positions) == len(files_to_add):
            # Insert files at their original positions to maintain date order
            for _, (file_path, position) in enumerate(zip(files_to_add, positions)):
                if file_path not in current_images:
                    if position <= len(current_images):
                        current_images.insert(position, file_path)
                    else:
                        current_images.append(file_path)
        else:
            # For files added to the end, add them incrementally
            for file_path in files_to_add:
                if file_path not in current_images:
                    current_images.append(file_path)
        model.set_displayed_images(current_images)
        
        # Update indices arrays
        self.populate_indices_arrays()
        
        # CRITICAL: Ensure highlight_index is synced from current_image_path after adding files
        # This guarantees file path is always the source of truth
        self.main_window._sync_highlight_index_from_current_image_path()
        
        # Use reorder_thumbnails to update the canvas with the new file list
        self.main_window.thumbnail_container.canvas.reorder_thumbnails(self.main_window.displayed_images, force_recalculate_grid=True)
        
        # Trigger thumbnail loading for the new files via cache manager
        for file_path in files_to_add:
            # Force thumbnail loading via cache manager with high priority
            self.main_window.cache_manager.get_thumbnail_async(file_path, self.main_window.current_thumbnail_size, priority=5)
    
    def get_image_info(self, image_path: str) -> tuple[str, int, int]:
        """Get image dimensions and file size"""
        try:
            from exif.exif_image_loader import get_image_dimensions_fast_metadata
            dimensions = get_image_dimensions_fast_metadata(image_path)
            if dimensions and len(dimensions) == 2:
                width, height = dimensions
                return (image_path, width, height)
        except Exception:
            pass
        return (image_path, 0, 0)
    
    def get_widget_count(self) -> int:
        """Get the number of widgets in the thumbnail container"""
        if hasattr(self.main_window, 'thumbnail_container') and self.main_window.thumbnail_container:
            return len(self.main_window.thumbnail_container.canvas.thumbnails) if hasattr(self.main_window.thumbnail_container.canvas, 'thumbnails') else 0
        return 0
    
    def find_thumbnail_index_by_path(self, path):
        """Find thumbnail index by file path"""
        if not self.main_window.displayed_images:
            return None
        try:
            return self.main_window.displayed_images.index(path)
        except ValueError:
            return None
    
    def set_thumbnail_size(self, size: int):
        """Set thumbnail size"""
        self.main_window.current_thumbnail_size = size
        self.main_window.manual_thumbnail_size = True
        self.generate_thumbnails(force_refresh=True)
    
    def set_dynamic_thumbnail_size(self):
        """Set thumbnail size dynamically based on available space"""
        if hasattr(self.main_window, 'thumbnail_operations_manager'):
            self.main_window.current_thumbnail_size, _, _ = self.main_window.thumbnail_operations_manager.calculate_grid_for_images(len(self.main_window.displayed_images))
            self.main_window.manual_thumbnail_size = False
    
    def _force_thumbnail_size_update(self, size: int):
        """Force thumbnail size update"""
        self.main_window.current_thumbnail_size = size
        if hasattr(self.main_window, 'thumbnail_container') and self.main_window.thumbnail_container:
            self.main_window.thumbnail_container.canvas.thumbnail_size = size
            self.main_window.thumbnail_container.canvas.calculate_grid_layout()
            self.main_window.thumbnail_container.canvas.update()
    
    def reorder_thumbnail_layout(self):
        """Reorder thumbnails without regenerating"""
        if hasattr(self.main_window, 'thumbnail_container') and self.main_window.thumbnail_container:
            self.main_window.thumbnail_container.canvas.reorder_thumbnails(self.main_window.displayed_images, force_recalculate_grid=True)
    
    def refresh_thumbnails_for_transformation(self):
        """Refresh thumbnails after image transformation"""
        # Invalidate cache for transformed images
        if hasattr(self.main_window, 'displayed_images') and self.main_window.displayed_images:
            for image_path in self.main_window.displayed_images:
                self.main_window.cache_manager.clear_cache_for_file(image_path)
        
        # Regenerate thumbnails
        self.generate_thumbnails(force_refresh=True)

    def on_thumbnail_loaded_from_worker(self, path, pixmap):
        """Handle thumbnail loaded signal from background worker"""
        mw = self.main_window
        thumbnail_index = mw.find_thumbnail_index_by_path(path)
        if thumbnail_index is not None:
            # set_thumbnail_loaded applies session transforms; do not pre-transform here
            mw.thumbnail_container.set_thumbnail_loaded(thumbnail_index, pixmap)

    def on_thumbnail_worker_finished(self):
        """Handle thumbnail loading finished signal from background worker"""
        mw = self.main_window
        mw.progress_bar.setVisible(False)
        QTimer.singleShot(0, lambda: mw.cache_manager.save_metadata_cache())
        if mw.status_bar:
            mw.status_bar_manager.clear_message()

    def on_thumbnail_worker_error(self):
        """Handle thumbnail loading error signal from background worker"""
        pass

    def on_thumbnail_progress_updated(self, completed, total, _):
        """Handle thumbnail loading progress updates"""
        mw = self.main_window
        if total > 0:
            if not mw.progress_bar.isVisible():
                mw.progress_bar.setVisible(True)
                mw.progress_bar.raise_()
            mw.progress_bar.setMaximum(total)
            mw.progress_bar.setValue(completed)
            mw.progress_bar.setFormat(f"Loading thumbnails: {completed}/{total}")
        else:
            mw.progress_bar.setVisible(False)
