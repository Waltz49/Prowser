#!/usr/bin/env python3
"""
Directory History Handler for Image Browser
Manages forward/backward navigation through previously visited directories
with complete state preservation and restoration.
"""

import os
import time
from typing import Dict, Any, Optional, List
from PySide6.QtCore import QTimer
from thumbnail_constants import MIN_THUMBNAIL_SIZE
from config import get_config

class DirectoryHistoryHandler:
    """Handles directory history navigation with state preservation"""
    
    def __init__(self, main_window):
        self.main_window = main_window
        self.backward_stack = []      # Previous states
        self.forward_stack = []       # Future states (after going back)
        self.max_history_size = 20    # Configurable limit
        self.tree_click_timer = None  # Timer for delayed tree click saves

    def _notify_status(self, message: str, timeout: int = 3000):
        """Helper to safely notify status if possible."""
        self.main_window.status_notification.show_message(message, timeout)
    def save_current_state(self, source: str, delay: float = 0.0):
        """Save current state with optional delay and duplicate optimization"""
        if delay > 0:
            # Cancel any existing timer
            if self.tree_click_timer:
                self.tree_click_timer.stop()
            
            # Set up delayed save
            self.tree_click_timer = QTimer()
            self.tree_click_timer.setSingleShot(True)
            self.tree_click_timer.timeout.connect(lambda: self._save_state_immediate(source))
            self.tree_click_timer.start(int(delay * 1000))
        else:
            self._save_state_immediate(source)
    
    def _save_state_immediate(self, source: str):
        """Immediately save the current state"""
        
        try:
            current_state = self.capture_current_state()
            if not current_state:
                return
            
            
            # Check for duplicates before adding
            is_duplicate = self.is_duplicate_state(current_state)
            if is_duplicate:
                return
            
            # Add to backward stack and clear forward stack
            self.backward_stack.append(current_state)
            self.forward_stack.clear()
            
            
            # Limit stack size
            if len(self.backward_stack) > self.max_history_size:
                removed = self.backward_stack.pop(0)
            
            # Optimize stacks to remove any remaining duplicates
            self._optimize_stacks()
            
        except Exception as e:
            pass # f"Error saving directory state: {e}")
            import traceback
            traceback.print_exc()
    
    def navigate_backward(self):
        """Pop previous state and restore it"""
    
        if not self.backward_stack:
            self._notify_status("No previous directories in history", 3000)
            return
        
        for i, state in enumerate(reversed(self.backward_stack)):
            specific_files = state.get('specific_files', [])
            specific_mode = f"Specific({len(specific_files)})" if specific_files else "Directory"
        
        current_state = self.capture_current_state()
        
        # Save current state before navigating
        if current_state and not self.is_duplicate_state(current_state):
            self.forward_stack.append(current_state)
        
        # Get previous state - if current state is duplicate, skip the duplicate
        previous_state = self.backward_stack.pop()
        
        # If the current state is a duplicate of the state we just popped,
        # skip it and get the next older state
        if current_state and self._is_duplicate_state_direct(current_state, previous_state):
            if self.backward_stack:
                previous_state = self.backward_stack.pop()
            else:
                # Put the state back since we can't navigate further
                self.backward_stack.append(previous_state)
                self._notify_status("Already at oldest state in history", 3000)
                return
        
        # Defer restoration to avoid blocking the event loop
        # This prevents hangs when restoring large directories
        def do_restore():
            # Restore the state using direct method for better control
            if self._restore_state_direct(previous_state):
                self._notify_status(f"Restored previous directory: {os.path.basename(previous_state['directory'])}", 3000)
            else:
                # If restoration failed, put the state back
                self.backward_stack.append(previous_state)
                self._notify_status("Failed to restore directory", 3000)
        
        QTimer.singleShot(0, do_restore)
    
    def navigate_forward(self):
        """Restore next state from forward stack"""
        if not self.forward_stack:
            self._notify_status("No next directories in history", 3000)
            return
        
        for i, state in enumerate(reversed(self.forward_stack)):
            specific_files = state.get('specific_files', [])
        
        current_state = self.capture_current_state()
        
        # Save current state before navigating
        if current_state and not self.is_duplicate_state(current_state):
            self.backward_stack.append(current_state)
        
        # Get next state
        next_state = self.forward_stack.pop()
        
        # Defer restoration to avoid blocking the event loop
        # This prevents hangs when restoring large directories
        def do_restore():
            # Restore the state using direct method for better control
            if self._restore_state_direct(next_state):
                self._notify_status(f"Restored next directory: {os.path.basename(next_state['directory'])}", 3000)
            else:
                # If restoration failed, put the state back
                self.forward_stack.append(next_state)
                self._notify_status("Failed to restore directory", 3000)
        
        QTimer.singleShot(0, do_restore)
    
    def capture_current_state(self) -> Optional[Dict[str, Any]]:
        """
        Capture complete current application state.

        What is saved:
        - Current directory
        - Limit and filter pattern
        - Selected files (paths), highlighted file
        - Specific files (if in specific files mode)
        - View mode (thumbnail, browse, etc.)
        - Thumbnail size
        - Main window geometry (x, y, width, height)
        - Timestamp
        """
        try:
            # Get current directory and settings
            # Get current directory from the first element of displayed_images, if available
            current_directory = None
            if hasattr(self.main_window, 'displayed_images'):
                displayed_images = getattr(self.main_window, 'displayed_images', [])
                if displayed_images:
                    current_directory = os.path.dirname(displayed_images[0])
            else:
                current_directory = getattr(self.main_window, 'current_directory', None)
            if not current_directory or not os.path.exists(current_directory):
                return None
            
            # Get current settings
            limit = getattr(self.main_window, 'limit', None)
            filter_pattern = getattr(self.main_window, 'filter_pattern', None)
            
            # Get selected files (full paths)
            selected_files = []
            selected_file = None
            if hasattr(self.main_window, 'selected_files') and hasattr(self.main_window, 'displayed_images'):
                selected_files = list(getattr(self.main_window, 'selected_files', set()))  # Already full paths
            
            # Get highlighted file (full path)
            if hasattr(self.main_window, 'highlight_index') and hasattr(self.main_window, 'displayed_images'):
                highlight_index = getattr(self.main_window, 'highlight_index', -1)
                displayed_images = getattr(self.main_window, 'displayed_images', [])
                if 0 <= highlight_index < len(displayed_images):
                    selected_file = displayed_images[highlight_index]  # Save full path
            
            # Capture specific files if we're in specific files mode
            # This is determined by checking if specific_files_active is True OR if we have specific files
            specific_files = []
            specific_files_active = getattr(self.main_window, 'specific_files_active', False)
            if specific_files_active and hasattr(self.main_window, 'displayed_images'):
                specific_files = self.main_window.displayed_images.copy()
            
            # Get view mode
            view_mode = 'thumbnail'  # Default
            if hasattr(self.main_window, 'slideshow_manager') and hasattr(self.main_window.slideshow_manager, 'is_active') and self.main_window.slideshow_manager.is_active():
                view_mode = 'slideshow'
            elif hasattr(self.main_window, 'current_view_mode'):
                view_mode = self.main_window.current_view_mode
            
            # Get thumbnail size
            thumbnail_size = MIN_THUMBNAIL_SIZE
            if hasattr(self.main_window, 'thumbnail_size'):
                thumbnail_size = self.main_window.thumbnail_size
            
            # Get window geometry
            window_geometry = {
                'x': self.main_window.x(),
                'y': self.main_window.y(),
                'width': self.main_window.width(),
                'height': self.main_window.height()
            }
            
            # Capture sort state using enum
            sort_state = {
                'sort_mode': getattr(self.main_window, 'current_sort_mode', None),
                'sort_mode_value': getattr(self.main_window.current_sort_mode, 'value', 'date') if hasattr(self.main_window, 'current_sort_mode') and self.main_window.current_sort_mode else 'date',
                'is_reversed': getattr(self.main_window, 'is_reversed', False),
            }
            
            state = {
                'directory': current_directory,
                'limit': limit,
                'filter_pattern': filter_pattern,
                'selected_file': selected_file,
                'selected_files': selected_files,
                'specific_files': specific_files,
                'view_mode': view_mode,
                'sort_state': sort_state,
            }
            return state
            
        except Exception as e:
            return None
    
    
    def _restore_state_direct(self, state: Dict[str, Any]) -> bool:
        """Restore state directly without API"""
        try:
            # Set flag to prevent clearing selections during history restoration
            self.main_window.restoring_from_history = True
            
            # Restore sort state FIRST, before loading directory, so load_directory sorts correctly
            self._restore_sort_state_immediate(state)
            
            # Check if this is a specific files state
            specific_files = state.get('specific_files', [])
            
            if specific_files:  # If we have specific files, we're in specific files mode
                # Load specific files instead of directory
                self.main_window.load_specific_files(specific_files, external_load=True)
                # Set limit and filter if they exist
                if state.get('limit') is not None:
                    self.main_window.limit = state['limit']
                if state.get('filter_pattern') is not None:
                    self.main_window.filter_pattern = state['filter_pattern']
                    # Update status bar immediately to reflect filter change
                    if hasattr(self.main_window, 'status_bar_manager'):
                        self.main_window.status_bar_manager._update_filter_section(self.main_window)
                
                # For specific files mode, we need to restore selections using the specific_files
                # Create a modified state with selected_files populated from specific_files
                # modified_state = state.copy()
                # modified_state['selected_files'] = specific_files
                
                # Restore selections after loading
                self._restore_selections(state)
                # Restore browse mode if that was the view when we left this level
                if state.get('view_mode') == 'browse' and state.get('selected_file'):
                    selected_file = state['selected_file']
                    if hasattr(self.main_window, 'displayed_images'):
                        for i, img_path in enumerate(self.main_window.displayed_images):
                            if img_path == selected_file:
                                self.main_window.view_mode_manager.open_browse_view(i)
                                break
                # Clear the flag after successful specific files restoration
                self.main_window.restoring_from_history = False
                return True
            
            # Handle browse mode restoration
            if state.get('view_mode') == 'browse' and state.get('selected_file'):
                # First load the directory
                self.main_window.load_directory(
                    state['directory'], 
                    external_load=True
                )
                # Set limit and filter if they exist
                if state.get('limit') is not None:
                    self.main_window.limit = state['limit']
                if state.get('filter_pattern') is not None:
                    self.main_window.filter_pattern = state['filter_pattern']
                    # Update status bar immediately to reflect filter change
                    if hasattr(self.main_window, 'status_bar_manager'):
                        self.main_window.status_bar_manager._update_filter_section(self.main_window)
                
                # Then find and open the specific file in browse
                if hasattr(self.main_window, 'displayed_images'):
                    for i, img_path in enumerate(self.main_window.displayed_images):
                        if img_path == state['selected_file']:
                            self.main_window.view_mode_manager.open_browse_view(i)
                            # Clear the flag after successful browse restoration
                            self.main_window.restoring_from_history = False
                            return True
                    # Clear the flag even if file not found
                    self.main_window.restoring_from_history = False
                    return False
            
            # For non-browse modes, use direct method for consistency
            self.main_window.load_directory(
                state['directory'], 
                external_load=True
            )
            # Set limit and filter if they exist
            if state.get('limit') is not None:
                self.main_window.limit = state['limit']
            if state.get('filter_pattern') is not None:
                self.main_window.filter_pattern = state['filter_pattern']
                # Update status bar immediately to reflect filter change
                if hasattr(self.main_window, 'status_bar_manager'):
                    self.main_window.status_bar_manager._update_filter_section(self.main_window)
            
            # Restore selections after loading
            self._restore_selections(state)
            return True
                
        except Exception as e:
            import traceback
            traceback.print_exc()
            return False
        finally:
            # Always clear the flag, even if an exception occurred
            self.main_window.restoring_from_history = False
    
    def is_duplicate_state(self, new_state: Dict[str, Any]) -> bool:
        """Check if new state is duplicate of most recent backward stack entry"""
        if not self.backward_stack:
            return False
        
        last_state = self.backward_stack[-1]
        return self._is_duplicate_state_direct(new_state, last_state)
    
    def _is_duplicate_state_direct(self, new_state: Dict[str, Any], compare_state: Dict[str, Any]) -> bool:
        """Check if two states are duplicates"""
        # Check if both states are specific files states
        new_specific_files = new_state.get('specific_files', [])
        compare_specific_files = compare_state.get('specific_files', [])
        
        if new_specific_files and compare_specific_files:
            # Both are specific files states - compare the specific files
            result = (new_specific_files == compare_specific_files and
                    new_state['limit'] == compare_state['limit'] and
                    new_state['filter_pattern'] == compare_state['filter_pattern'])
            return result
        elif not new_specific_files and not compare_specific_files:
            # Both are directory states - compare directory, limit, and filter
            result = (new_state['directory'] == compare_state['directory'] and
                    new_state['limit'] == compare_state['limit'] and
                    new_state['filter_pattern'] == compare_state['filter_pattern'])
            return result
        else:
            # One is specific files, one is directory - they're different
            return False
    
    def _optimize_stacks(self):
        """Remove duplicate directory/limit/filter combinations from stacks"""
        # For now, don't optimize stacks to avoid removing valid states
        # The duplicate detection in _is_duplicate_state is sufficient
        pass
    
    def _restore_sort_state_immediate(self, state: Dict[str, Any]):
        """Restore sort state using enum immediately (before directory loading)"""
        try:
            sort_state = state.get('sort_state', {})
            if not sort_state:
                return
            
            # Restore sort mode using enum
            if hasattr(self.main_window, 'current_sort_mode'):
                from image_browser_window import SortMode
                sort_mode_value = sort_state.get('sort_mode_value')
                if sort_mode_value:
                    try:
                        # Map string value to enum (must include all SortMode values)
                        mode_map = {
                            'date': SortMode.DATE,
                            'name': SortMode.NAME,
                            'size': SortMode.SIZE,
                            'dimensions': SortMode.DIMENSIONS,
                            'custom': SortMode.CUSTOM,
                            'random': SortMode.RANDOM,
                            'duplicates': SortMode.DUPLICATES,
                            'exif_date': SortMode.EXIF_DATE,
                            'exif_year': SortMode.EXIF_YEAR,
                            'filesize': SortMode.FILESIZE,
                            'permissions': SortMode.PERMISSIONS,
                        }
                        self.main_window.current_sort_mode = mode_map.get(sort_mode_value, SortMode.DATE)
                        # Explicitly clear duplicate_sections if not in DUPLICATES mode
                        if hasattr(self.main_window, 'duplicate_sections'):
                            if self.main_window.current_sort_mode != SortMode.DUPLICATES:
                                self.main_window.duplicate_sections = []
                                # Force canvas repaint to update thumbnail formatting
                                if hasattr(self.main_window, 'thumbnail_container') and self.main_window.thumbnail_container:
                                    if hasattr(self.main_window.thumbnail_container, 'canvas'):
                                        self.main_window.thumbnail_container.canvas.update()
                    except Exception:
                        self.main_window.current_sort_mode = SortMode.DATE
                        # Explicitly clear duplicate_sections if not in DUPLICATES mode
                        if hasattr(self.main_window, 'duplicate_sections'):
                            self.main_window.duplicate_sections = []
                            # Force canvas repaint to update thumbnail formatting
                            if hasattr(self.main_window, 'thumbnail_container') and self.main_window.thumbnail_container:
                                if hasattr(self.main_window.thumbnail_container, 'canvas'):
                                    self.main_window.thumbnail_container.canvas.update()
                else:
                    self.main_window.current_sort_mode = SortMode.DATE
                    # Explicitly clear duplicate_sections if not in DUPLICATES mode
                    if hasattr(self.main_window, 'duplicate_sections'):
                        self.main_window.duplicate_sections = []
                        # Force canvas repaint to update thumbnail formatting
                        if hasattr(self.main_window, 'thumbnail_container') and self.main_window.thumbnail_container:
                            if hasattr(self.main_window.thumbnail_container, 'canvas'):
                                self.main_window.thumbnail_container.canvas.update()
            
            # Restore reversed flag
            self.main_window.is_reversed = sort_state.get('is_reversed', False)

        except Exception as e:
            pass # f"Error restoring sort state: {e}"
    
    def _restore_selections(self, state: Dict[str, Any]):
        """Restore selections after directory loading"""
        try:
            selected_files = state.get('selected_files', [])
            
            if not selected_files:
                return
            
            # Wait longer for the directory to load and widgets to be created
            from PySide6.QtCore import QTimer
            QTimer.singleShot(100, lambda: self._do_restore_selections(selected_files, state))
            
        except Exception as e:
            pass # f"Error restoring selections: {e}")
            
    def _do_restore_selections(self, selected_files: List[str], state: Dict[str, Any]):
        """Actually restore the selections after delay"""
        try:
            if not hasattr(self.main_window, 'displayed_images') or not self.main_window.displayed_images:
                return
            
            
            # Clear selections gently without triggering highlight updates
            self.main_window.selected_files.clear()
            self.main_window.range_anchor_index = None
            
            # Restore selections using file names directly
            displayed_images = self.main_window.displayed_images
            restored_files = set()
            
            last_selected_index = None
            for i, image_path in enumerate(displayed_images):
                # Compare full paths since selected_files contains full paths
                if image_path in selected_files:
                    restored_files.add(image_path)
                    last_selected_index = i  # Track last selected index for highlighting
            
            # Set the selections using file names
            self.main_window.selected_files = restored_files
            
            # multi_select_mode is now automatically derived from selected_files
            
            # Set highlight index to the last selected file
            if last_selected_index is not None:
                self.main_window.highlight_index = last_selected_index
                self.main_window._emit_selection_changed(highlight_index=last_selected_index)
            
            # Ensure the highlighted item's file is also in selected_files (so it shows as selected/gold)
            if hasattr(self.main_window, 'highlight_index') and hasattr(self.main_window, 'displayed_images'):
                highlight_index = getattr(self.main_window, 'highlight_index', -1)
                if highlight_index >= 0 and highlight_index < len(self.main_window.displayed_images):
                    highlighted_file = self.main_window.displayed_images[highlight_index]
                    if highlighted_file not in self.main_window.selected_files:
                        self.main_window.selected_files.add(highlighted_file)
            
            # Update the UI to show selections visually
            self._update_thumbnail_selections()
            
            # Force canvas update to ensure visual changes are applied
            self._force_canvas_update()
            
            # Add a small delay and force another update to ensure visual changes are applied
            from PySide6.QtCore import QTimer
            QTimer.singleShot(100, lambda: self._force_canvas_update())
            QTimer.singleShot(200, lambda: self.main_window.thumbnail_container.scroll_to_highlighted(last_selected_index))
            
        except Exception as e:
            pass # f"Error in _do_restore_selections: {e}")
    
    def _update_thumbnail_selections(self):
        """Update the visual highlighting of all selected thumbnails"""
        try:
            selected_files = self.main_window.selected_files
            
            # Update canvas-based selections using centralized method
            # multi_select_mode is now automatically derived from selected_files
            self.main_window._emit_selection_changed()
            
            
        except Exception as e:
            pass # f"Error updating thumbnail selections: {e}")
    
    def _force_canvas_update(self):
        """Force a canvas update after a delay to ensure visual changes are applied"""
        try:
            if hasattr(self.main_window, 'thumbnail_container') and self.main_window.thumbnail_container:
                if hasattr(self.main_window.thumbnail_container, 'canvas'):
                    self.main_window.thumbnail_container.canvas.update()
                elif hasattr(self.main_window.thumbnail_container, 'force_canvas_size_update'):
                    self.main_window.thumbnail_container.force_canvas_size_update()
                else:
                    self.main_window.thumbnail_container.update()
        except Exception as e:
            pass # f"Error in _force_canvas_update: {e}")
    
    def cleanup(self):
        """Clean up resources"""
        if self.tree_click_timer:
            self.tree_click_timer.stop()
            self.tree_click_timer = None


class DirectoryHistoryHandlerForMenu:
    """Handles directory history for menu display"""
    def __init__(self): 
        self.max_history_size = 20
        self.config = get_config()
        self.directory_history = self.config.load_settings().get('directory_menu_history', [])
        
    def add_directory(self, path: str):
        if not path:
            return
        path = os.path.dirname(os.path.normpath(path))
        if not os.path.exists(path):
            return
        if not os.path.isdir(path):
            return
        if path in self.directory_history:
            self.directory_history.remove(path)
        self.directory_history.append(path)
        if len(self.directory_history) > self.max_history_size:
            self.directory_history.pop(0)
        get_config().update_setting('directory_menu_history', self.directory_history)    
    
    def clear_history(self):
        self.directory_history = []