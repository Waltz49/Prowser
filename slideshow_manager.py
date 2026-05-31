#!/usr/bin/env python3
"""
Slideshow Manager for the first slideshow (S key) - extracted from ImageBrowserWindow
Similar to Slideshow2Manager, manages slideshow state and functionality
"""

# Standard library imports
import os
import random
import math

# Third-party imports
from PySide6.QtCore import (
    Qt, QTimer, QPropertyAnimation, QEasingCurve, QPoint, Property, QObject
)
from PySide6.QtGui import QPixmap, QKeyEvent, QTransform
from PySide6.QtWidgets import QGraphicsOpacityEffect
from PySide6.QtWidgets import QLabel

# Local imports
from config import get_config as _get_config

class SlideshowManager:
    """Manages slideshow functionality, extracted from ImageBrowserWindow.
    Similar to Slideshow2Manager, manages its own slideshow state and settings.
    """

    def __init__(self, window):
        """Initialize slideshow manager"""
        super().__setattr__('window', window)
        
        # Load slideshow settings from config (lazy load to allow profile directory to be set first)
        self.main_window = window
        self.config = _get_config()
        settings = self.config.load_settings()
        self.slideshow_rate = settings.get('slideshow_rate', 5000)
        self.slideshow_transition_speed = settings.get('slideshow_transition_speed', 1300)
        self.slideshow_direction = settings.get('slideshow_direction', 'right')
        self.slideshow_max_rotation = settings.get('slideshow_max_rotation', 0)
        self.slideshow_overlap_delay = settings.get('slideshow_overlap_delay', -200)
        self.slideshow_back_and_forth = settings.get('slideshow_back_and_forth', False)
        
        # Initialize slideshow state attributes
        # Note: slideshow state is now tracked via window.current_view_mode == 'slideshow'
        self.slideshow_timer = QTimer()
        self.slideshow_timer.timeout.connect(self.advance_slideshow)
        
        # Animation references to prevent garbage collection
        self._current_slideshow_anim = None
        self._next_slideshow_anim = None
        self._current_rotation_anim = None
        self._next_rotation_anim = None
        self._current_opacity_anim = None
        
        # Slideshow images list - tracks which images to show in slideshow
        # If multiselect is active, this contains only selected images
        # Otherwise, contains all displayed images
        self._slideshow_images = []
        self._slideshow_current_index = 0
        self._slideshow_step_direction = 1
        self._slideshow_at_endpoint_repeat = False
        
        # Debounced save mechanism for slideshow settings
        self._save_timer = QTimer()
        self._save_timer.setSingleShot(True)
        self._save_timer.timeout.connect(self._save_pending_settings)
        self._pending_settings = {}  # Settings waiting to be saved
        self._save_delay = 1000  # 1 second delay before saving

    def save_slideshow_settings(self):
        """Save slideshow settings to config"""
        self.config.update_setting('slideshow_rate', self.slideshow_rate)
        self.config.update_setting('slideshow_transition_speed', self.slideshow_transition_speed)
        self.config.update_setting('slideshow_direction', self.slideshow_direction)
        self.config.update_setting('slideshow_max_rotation', self.slideshow_max_rotation)
        self.config.update_setting('slideshow_overlap_delay', self.slideshow_overlap_delay)
        self.config.update_setting('slideshow_back_and_forth', self.slideshow_back_and_forth)

    def debounced_save_setting(self, key: str, value):
        """Save a setting with debouncing to avoid excessive disk writes"""
        self._pending_settings[key] = value
        
        # Reset the timer - this will delay the save
        self._save_timer.stop()
        self._save_timer.start(self._save_delay)
    
    def _save_pending_settings(self):
        """Save all pending settings to disk"""
        if not self._pending_settings:
            return
            
        try:
            for key, value in self._pending_settings.items():
                self.config.update_setting(key, value)
            self._pending_settings.clear()
        except Exception as e:
            print(f"Failed to save slideshow settings: {e}")

    def update_slideshow_settings(self, new_settings):
        """Update slideshow settings from settings dialog"""
        if 'slideshow_rate' in new_settings:
            self.slideshow_rate = new_settings['slideshow_rate']
            # Update timer interval if slideshow is running
            if self.window.current_view_mode == 'slideshow' and self.slideshow_timer.isActive():
                self.slideshow_timer.setInterval(self.slideshow_rate)
        
        if 'slideshow_transition_speed' in new_settings:
            self.slideshow_transition_speed = new_settings['slideshow_transition_speed']
        
        if 'slideshow_direction' in new_settings:
            self.slideshow_direction = new_settings['slideshow_direction']
        
        if 'slideshow_max_rotation' in new_settings:
            self.slideshow_max_rotation = new_settings['slideshow_max_rotation']
        
        if 'slideshow_overlap_delay' in new_settings:
            self.slideshow_overlap_delay = new_settings['slideshow_overlap_delay']

        if 'slideshow_back_and_forth' in new_settings:
            was_enabled = self.slideshow_back_and_forth
            self.slideshow_back_and_forth = new_settings['slideshow_back_and_forth']
            if self.slideshow_back_and_forth and (
                not was_enabled or self.window.current_view_mode == 'slideshow'
            ):
                self._reset_slideshow_ping_pong_state()

    def cleanup(self):
        """Clean up resources and save any pending settings"""
        # Force save any pending settings
        self._save_pending_settings()
        
        # Stop slideshow if running
        if self.window.current_view_mode == 'slideshow':
            self.stop_slideshow()
        
        # Clean up timers
        if hasattr(self, '_save_timer'):
            self._save_timer.stop()
            self._save_timer.deleteLater()

    # --------------------------------------------------
    # State management - using current_view_mode as source of truth
    # slideshow_running property removed - use window.current_view_mode == 'slideshow' directly
    # --------------------------------------------------
    
    # --------------------------------------------------
    # Generic attribute proxy helpers - for compatibility
    # --------------------------------------------------
    def __getattr__(self, name):
        return getattr(self.window, name)

    def __setattr__(self, name, value):
        if name == 'window':
            super().__setattr__(name, value)
        elif name in ['slideshow_timer', 'slideshow_rate', 
                     'slideshow_transition_speed', 'slideshow_direction', 'slideshow_max_rotation',
                     'slideshow_overlap_delay', 'slideshow_back_and_forth',
                     '_slideshow_step_direction', '_slideshow_at_endpoint_repeat',
                     '_current_slideshow_anim', '_next_slideshow_anim',
                     '_current_rotation_anim', '_next_rotation_anim', '_current_opacity_anim']:
            # These slideshow attributes are managed locally in the manager
            super().__setattr__(name, value)
        else:
            setattr(self.window, name, value)

    # --------------------------------------------------
    # Main slideshow control methods
    # --------------------------------------------------
    
    def toggle_slideshow(self):
        """Toggle slideshow mode"""
        # Stop other slideshows if running
        if hasattr(self.window, "slideshow2_manager") and \
           self.window.current_view_mode == 'slideshow2':
            self.window.slideshow2_manager.stop_slideshow2()
        if hasattr(self.window, "slideshow3_manager") and \
           self.window.current_view_mode == 'slideshow3':
            self.window.slideshow3_manager.stop_slideshow3()

        # Determine which images to use for slideshow
        # If multiselect is active, use selected images; otherwise use displayed thumbnails
        if hasattr(self.window, 'multi_select_mode') and self.window.multi_select_mode:
            # Use selected images
            slideshow_images = sorted(list(self.window.selected_files)) if hasattr(self.window, 'selected_files') else []
        else:
            # Use displayed thumbnails
            slideshow_images = self.get_displayed_images() if hasattr(self, 'get_displayed_images') else []
        
        if not slideshow_images:
            return
            
        if self.window.current_view_mode == 'slideshow':
            self.stop_slideshow()
        else:
            self.start_slideshow()

    def start_slideshow(self):
        """Start slideshow mode"""
        # Determine which images to use for slideshow
        # If multiselect is active, use selected images; otherwise use displayed thumbnails
        if hasattr(self.window, 'multi_select_mode') and self.window.multi_select_mode:
            # Use selected images
            slideshow_images = sorted(list(self.window.selected_files)) if hasattr(self.window, 'selected_files') else []
        else:
            # Use displayed thumbnails
            slideshow_images = self.get_displayed_images() if hasattr(self, 'get_displayed_images') else []
        
        if not slideshow_images:
            return
        
        # Apply sort/random without lock restrictions for slideshow order
        # (slideshow does not keep locked files in place - all images are sorted together)
        if hasattr(self.window, 'sorting_manager') and self.window.sorting_manager:
            directory = os.path.dirname(slideshow_images[0]) if slideshow_images else None
            slideshow_images = self.window.sorting_manager.apply_display_order(
                slideshow_images, directory, skip_locks=True)
        
        # Store the slideshow images list
        self._slideshow_images = slideshow_images
        
        # Find the current image in the slideshow list
        current_image_path = self.window.get_current_image_path() if hasattr(self.window, 'get_current_image_path') else None
        if current_image_path and current_image_path in self._slideshow_images:
            self._slideshow_current_index = self._slideshow_images.index(current_image_path)
        else:
            self._slideshow_current_index = 0

        self._reset_slideshow_ping_pong_state()
        
        # Stop other slideshows if running
        if hasattr(self.window, 'slideshow2_manager') and self.window.current_view_mode == 'slideshow2':
            self.window.slideshow2_manager.stop_slideshow2()
        if hasattr(self.window, 'slideshow3_manager') and self.window.current_view_mode == 'slideshow3':
            self.window.slideshow3_manager.stop_slideshow3()
            
        self.current_view_mode = 'slideshow'
        
        self.window.right_sidebar.hide_image_info_overlay()
        self.window.update_number_overlay()
        
        # Manage sidebar visibility for slideshow mode
        self.main_window.manage_sidebar_visibility_for_view_mode('slideshow')
        
        # Switch to fullscreen view for slideshow
        self.stacked_widget.setCurrentIndex(1)  # Switch to fullscreen widget
        
        # Set browse view widget background to black for slideshow mode
        if getattr(self, 'stacked_widget', None) and self.stacked_widget.count() > 1:
            browse_view_widget = self.stacked_widget.widget(1)
            if browse_view_widget:
                browse_view_widget.setStyleSheet("""
                    QWidget {
                        background-color: rgb(0, 0, 0);
                        color: white;
                    }
                """)
        
        # Hide status bar for slideshow mode
        if hasattr(self.main_window, 'status_bar') and self.main_window.status_bar.isVisible():
            self.main_window.status_bar.hide()
        
        # Update status bar sections for slideshow mode
        if hasattr(self.window, 'update_status_bar_sections'):
            self.window.update_status_bar_sections()
        
        # Update menu states to ensure shortcuts are properly enabled/disabled
        if hasattr(self.main_window, 'menu_manager'):
            self.main_window.menu_manager.update_view_menu_enabled_states()
            self.main_window.menu_manager.update_edit_menu_states()
            self.main_window.menu_manager.update_tools_menu_states()
            self.main_window.menu_manager.update_search_menu_states()
        
        # Initialize and start cursor manager for slideshow mode
        self.main_window.view_manager._setup_cursor_manager()
        
        # Ensure the widget is properly sized before setting up slideshow
        QTimer.singleShot(10, self.setup_slideshow_layout)
        
        # Update status
        if self.status_notification:
            self.status_notification.show_message(
                f"Slideshow started - {self.slideshow_rate}ms intervals"
            )

    def setup_slideshow_layout(self):
        """Set up slideshow layout after widget is ready"""
        # Force update of layout
        self.stacked_widget.widget(1).updateGeometry()  # Update fullscreen widget
        
        # Ensure image_container is properly sized (slideshow2 might have changed it)
        if getattr(self, 'image_container', None):
            container_size = self.image_container.size()
            if container_size.width() < 100 or container_size.height() < 100:
                # Use effective display size to account for tree view and status bar
                if hasattr(self.window, 'get_effective_display_size'):
                    container_size = self.window.get_effective_display_size()
                    self.image_container.resize(container_size)
                else:
                    container_size = self.size()
                    self.image_container.resize(container_size)
        
        # Reset image label to ensure clean state after slideshow2
        if getattr(self, 'image_label', None):
            self.image_label.clear()
            # Reset to normal fullscreen size and position
            container_size = self.image_container.size()
            if container_size.width() < 100 or container_size.height() < 100:
                # Use effective display size to account for tree view and status bar
                if hasattr(self.window, 'get_effective_display_size'):
                    container_size = self.window.get_effective_display_size()
                else:
                    container_size = self.size()
            self.image_label.resize(container_size)
            self.image_label.move(0, 0)
        
        # Reset slideshow_next_label to ensure clean state after slideshow2
        if getattr(self, 'slideshow_next_label', None):
            self.slideshow_next_label.hide()
            self.slideshow_next_label.clear()
            self.slideshow_next_label.setGraphicsEffect(None)
            # Ensure it's in the layout
            if hasattr(self, 'image_layout'):
                layout = self.image_layout
                next_label_in_layout = False
                for i in range(layout.count()):
                    item = layout.itemAt(i)
                    if item and item.widget() == self.slideshow_next_label:
                        next_label_in_layout = True
                        break
                if not next_label_in_layout:
                    layout.addWidget(self.slideshow_next_label)
        
        # Ensure slideshow labels are properly positioned
        self.update_slideshow_labels_position()
        
        # Use the slideshow images list (set in start_slideshow)
        if self._slideshow_images and 0 <= self._slideshow_current_index < len(self._slideshow_images):
            image_path = self._slideshow_images[self._slideshow_current_index]
            self.show_slideshow_image(image_path, self._slideshow_current_index)
        
        # Start the slideshow timer after setup is complete
        
        self.slideshow_timer.start(self.slideshow_rate)

    def stop_slideshow(self):
        """Stop slideshow mode"""
        # If not in slideshow, we're being called defensively (e.g. from open_current_browse_view).
        # Return early to avoid apply_current_sort() which would overwrite similarity search order.
        if getattr(self.main_window, 'current_view_mode', None) != 'slideshow':
            self.slideshow_timer.stop()
            return
        
        self.slideshow_timer.stop()
        
        # Stop any running animations
        if getattr(self, '_current_slideshow_anim', None):
            self._current_slideshow_anim.stop()
        if getattr(self, '_next_slideshow_anim', None):
            self._next_slideshow_anim.stop()
        if getattr(self, '_current_rotation_anim', None):
            self._current_rotation_anim.stop()
        if getattr(self, '_next_rotation_anim', None):
            self._next_rotation_anim.stop()
        if getattr(self, '_current_opacity_anim', None):
            self._current_opacity_anim.stop()
        
        # Hide and reset the next label
        if hasattr(self, 'slideshow_next_label'):
            self.slideshow_next_label.hide()
        
        # Reset image label to normal fullscreen layout
        self.reset_image_label_for_fullscreen()
        
        # Reset opacity of image label and remove graphics effect
        if hasattr(self, 'image_label'):
            self.image_label.setGraphicsEffect(None)
        
        # Restore browse view widget background to black (borders must remain black)
        if getattr(self, 'stacked_widget', None) and self.stacked_widget.count() > 1:
            browse_view_widget = self.stacked_widget.widget(1)
            if browse_view_widget:
                browse_view_widget.setStyleSheet(f"""
                    QWidget {{
                        background-color: rgb(0, 0, 0);
                        color: white;
                    }}
                """)
        
        # Return to thumbnail view
        self.current_view_mode = 'thumbnail'
        
        # Re-apply sort with lock restrictions (slideshow uses no-locks order)
        if hasattr(self.main_window, 'sorting_manager') and self.main_window.sorting_manager:
            self.main_window.sorting_manager.apply_current_sort()
        
        self.stacked_widget.setCurrentIndex(0)  # Switch back to thumbnail view
        
        # Restore sidebar when returning to thumbnail mode
        self.main_window.manage_sidebar_visibility_for_view_mode('thumbnail')
        
        # Restore status bar visibility based on config setting
        if hasattr(self.main_window, 'status_bar'):
            settings = self.config.load_settings()
            status_bar_visible = settings.get('status_bar_visible', True)
            if status_bar_visible:
                self.main_window.status_bar.show()
            else:
                self.main_window.status_bar.hide()
        
        # Update status bar sections for thumbnail mode
        if hasattr(self.window, 'update_status_bar_sections'):
            self.window.update_status_bar_sections()
        
        # Prime and enable menu keys for view change
        if hasattr(self.main_window, 'menu_manager'):
            self.main_window.menu_manager.prime_menu_keys_for_view_change()
        
        # Efficiently refresh directory to show any added/removed files
        QTimer.singleShot(100, self.main_window.efficient_directory_refresh)
        
        # Clean up cursor manager
        if hasattr(self.main_window, 'cursor_manager') and self.main_window.cursor_manager:
            self.main_window.cursor_manager.cleanup()
            self.main_window.cursor_manager = None
        
        # Force save any pending settings before stopping
        self._save_pending_settings()
        
        # Clean up slideshow images list
        self._slideshow_images = []
        self._slideshow_current_index = 0
        self._slideshow_step_direction = 1
        self._slideshow_at_endpoint_repeat = False

    def _reset_slideshow_ping_pong_state(self):
        """Initialize ping-pong direction from current index (forward unless at last image)."""
        n = len(self._slideshow_images)
        idx = self._slideshow_current_index
        self._slideshow_at_endpoint_repeat = False
        if n <= 1:
            self._slideshow_step_direction = 1
            return
        if idx >= n - 1:
            self._slideshow_step_direction = -1
        else:
            self._slideshow_step_direction = 1

    def _advance_slideshow_index(self):
        """Move to the next slideshow index (loop or back-and-forth)."""
        n = len(self._slideshow_images)
        if n <= 1:
            return

        if not self.slideshow_back_and_forth:
            self._slideshow_current_index = (self._slideshow_current_index + 1) % n
            return

        idx = self._slideshow_current_index
        direction = self._slideshow_step_direction

        if direction == 1:
            if idx < n - 1:
                self._slideshow_current_index = idx + 1
            elif not self._slideshow_at_endpoint_repeat:
                self._slideshow_at_endpoint_repeat = True
            else:
                self._slideshow_at_endpoint_repeat = False
                self._slideshow_step_direction = -1
                self._slideshow_current_index = idx - 1
        else:
            if idx > 0:
                self._slideshow_current_index = idx - 1
            elif not self._slideshow_at_endpoint_repeat:
                self._slideshow_at_endpoint_repeat = True
            else:
                self._slideshow_at_endpoint_repeat = False
                self._slideshow_step_direction = 1
                self._slideshow_current_index = idx + 1

    def _sync_slideshow_images_from_displayed(self):
        """Sync slideshow image list from displayed_images when sort mode changes during slideshow.
        Ensures slideshow order and thumbnail view stay in sync."""
        displayed = self.window.get_displayed_images() if hasattr(self.window, 'get_displayed_images') else []
        if not displayed:
            return
        current_path = self.window.get_current_image_path() if hasattr(self.window, 'get_current_image_path') else None
        self._slideshow_images = displayed.copy()
        if current_path and current_path in self._slideshow_images:
            self._slideshow_current_index = self._slideshow_images.index(current_path)
        else:
            self._slideshow_current_index = 0
        if self.slideshow_back_and_forth:
            self._reset_slideshow_ping_pong_state()

    def advance_slideshow(self):
        """Advance to next slide in slideshow"""
        # Use the slideshow images list (set in start_slideshow)
        if self.window.current_view_mode != 'slideshow' or not self._slideshow_images:
            return
        
        # Check if an animation is still running - if so, skip this advance
        if (getattr(self, '_next_slideshow_anim', None) and 
            self._next_slideshow_anim.state() == QPropertyAnimation.Running):
            return
        if (getattr(self, '_current_opacity_anim', None) and 
            self._current_opacity_anim.state() == QPropertyAnimation.Running):
            return
            
        self._advance_slideshow_index()
        
        # Note: Don't call highlight_image() here during slideshow to avoid interference
        # It will be called after animation finishes in slideshow_animation_finished()
        
        # Show next image with animation
        if 0 <= self._slideshow_current_index < len(self._slideshow_images):
            image_path = self._slideshow_images[self._slideshow_current_index]
            # --- MODIFIED SECTION FOR 'none' ---
            self.show_slideshow_image_with_animation(image_path, self._slideshow_current_index)
            
            # Update window title to show the full path of the active image
            self.main_window.image_display_manager.update_window_title_for_active_image()

    def update_slideshow_labels_position(self):
        """Update positions of slideshow image labels to fit image content exactly"""
        if hasattr(self, 'image_container'):
            container_size = self.image_container.size()
            
            # Ensure container has a reasonable size
            if container_size.width() < 200 or container_size.height() < 200:
                # Force the container to use the full widget size
                browse_view_widget = self.stacked_widget.widget(1)  # Get browse view widget
                if browse_view_widget:
                    container_size = browse_view_widget.size()
                    self.image_container.resize(container_size)
            
            # Update both labels to the container size
            if hasattr(self, 'slideshow_next_label'):
                self.slideshow_next_label.resize(container_size)
                self.slideshow_next_label.move(0, 0)

    def show_slideshow_image(self, image_path: str, index: int):
        """Show slideshow image without animation"""
        # Update current_image_path immediately
        self.current_image_path = image_path
        
        try:
            # Load the image with EXIF correction
            try:
                from slideshow_image_loader import load_slideshow_pixmap
                from config import get_config
                config = get_config()
                settings = config.load_settings()
                ignore_exif = settings.get('ignore_exif_rotation', False)
                pixmap = load_slideshow_pixmap(str(image_path), ignore_exif=ignore_exif)
            except ImportError:
                # Fallback to direct loading if exif_image_loader not available
                pixmap = QPixmap(str(image_path))
            
            if pixmap.isNull():
                return
                    
            # Scale to fit screen while maintaining aspect ratio
            container_size = self.image_container.size()
            
            if container_size.width() < 100 or container_size.height() < 100:
                # Use effective display size to account for tree view and status bar
                if hasattr(self.window, 'get_effective_display_size'):
                    container_size = self.window.get_effective_display_size()
                else:
                    container_size = self.size()
            
            scaled_pixmap = pixmap.scaled(
                container_size,
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation
            )
            
            # Calculate extra space needed for rotation if enabled
            if self.slideshow_max_rotation == 0:
                label_size = scaled_pixmap.size()
            else:
                # Calculate the diagonal to accommodate any rotation
                diagonal = int(math.sqrt(scaled_pixmap.width()**2 + scaled_pixmap.height()**2))
                from PySide6.QtCore import QSize
                label_size = QSize(diagonal, diagonal)
            
            # Resize and center the image label
            self.image_label.resize(label_size)
            center_x = (container_size.width() - label_size.width()) // 2
            center_y = (container_size.height() - label_size.height()) // 2
            self.image_label.move(center_x, center_y)
            
            # Set the image on the main label and store as original for rotation
            self.image_label.setPixmap(scaled_pixmap)
            self.image_label.original_pixmap = scaled_pixmap
            
        except Exception as e:
            print(f"Error loading slideshow image: {e}")

    def show_slideshow_image_with_animation(self, image_path: str, index: int):
        """Show next slideshow image with directional animation and rotation"""
        # Update current_image_path immediately so highlight_image() in slideshow_animation_finished() uses the correct path
        self.current_image_path = image_path
        
        # Load the new image with EXIF correction
        try:
            from slideshow_image_loader import load_slideshow_pixmap
            from config import get_config
            config = get_config()
            settings = config.load_settings()
            ignore_exif = settings.get('ignore_exif_rotation', False)
            pixmap = load_slideshow_pixmap(str(image_path), ignore_exif=ignore_exif)
        except ImportError:
            # Fallback to direct loading if exif_image_loader not available
            pixmap = QPixmap(str(image_path))
        
        if pixmap.isNull():
            return
        
        # Scale to fit screen while maintaining aspect ratio
        container_size = self.image_container.size()
        
        if container_size.width() < 100 or container_size.height() < 100:
            # Use effective display size to account for tree view and status bar
            if hasattr(self.window, 'get_effective_display_size'):
                container_size = self.window.get_effective_display_size()
            else:
                container_size = self.size()
            
        scaled_pixmap = pixmap.scaled(
            container_size,
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation
        )

        # Stop any running animations first to prevent conflicts
        if getattr(self, '_current_slideshow_anim', None):
            self._current_slideshow_anim.stop()
        if getattr(self, '_next_slideshow_anim', None):
            self._next_slideshow_anim.stop()
        if getattr(self, '_current_rotation_anim', None):
            self._current_rotation_anim.stop()
        if getattr(self, '_next_rotation_anim', None):
            self._next_rotation_anim.stop()
        if getattr(self, '_current_opacity_anim', None):
            self._current_opacity_anim.stop()
        
        # Get current image size for proper label sizing
        current_pixmap = self.image_label.pixmap()
        current_image_size = current_pixmap.size() if current_pixmap else scaled_pixmap.size()
        next_image_size = scaled_pixmap.size()
        
        # Size labels to exactly fit their image content (with extra space for rotation)
        
        # Calculate extra space needed for rotation
        def get_label_size_for_rotation(image_size, max_rotation):
            if max_rotation == 0:
                return image_size
            # Calculate the diagonal to accommodate any rotation
            diagonal = int(math.sqrt(image_size.width()**2 + image_size.height()**2))
            from PySide6.QtCore import QSize
            return QSize(diagonal, diagonal)
        
        current_label_size = get_label_size_for_rotation(current_image_size, self.slideshow_max_rotation)
        next_label_size = get_label_size_for_rotation(next_image_size, self.slideshow_max_rotation)
        
        # Only resize the incoming label - keep the outgoing label at its current size
        if hasattr(self, 'slideshow_next_label'):
            next_label = self.slideshow_next_label
        else:
            return  # Can't animate without it

        next_label.resize(next_label_size)
        
        current_center_x = (container_size.width() - current_label_size.width()) // 2
        current_center_y = (container_size.height() - current_label_size.height()) // 2
        next_center_x = (container_size.width() - next_label_size.width()) // 2
        next_center_y = (container_size.height() - next_label_size.height()) // 2
        next_center_pos = QPoint(next_center_x, next_center_y)
        
        # Store original pixmaps for rotation animation
        if not hasattr(self.image_label, 'original_pixmap'):
            self.image_label.original_pixmap = current_pixmap
        
        # Set up the next image label
        next_label.setPixmap(scaled_pixmap)
        next_label.original_pixmap = scaled_pixmap
        
        # Temporarily remove from layout to allow manual positioning
        if hasattr(self, 'image_layout'):
            self.image_layout.removeWidget(next_label)
            next_label.setParent(self.image_container)
        
        next_label.show()
        
        direction = self.slideshow_direction

        # If the direction is 'none', do a crossfade and don't animate position
        if direction == 'none':
            fade_duration = self.slideshow_transition_speed
            if fade_duration == 0:
                # Don't fade; instantly switch
                self.show_slideshow_image(image_path, index)
                self.highlight_image()
                self.main_window.image_display_manager.update_window_title_for_active_image()
                return

            # Place next_label on top of image_label
            next_label.move(next_center_x, next_center_y)
            # Outgoing label effect
            out_op_effect = QGraphicsOpacityEffect(self.image_label)
            self.image_label.setGraphicsEffect(out_op_effect)
            out_op_effect.setOpacity(1.0)
            # Incoming (next) label effect
            in_op_effect = QGraphicsOpacityEffect(next_label)
            next_label.setGraphicsEffect(in_op_effect)
            in_op_effect.setOpacity(0.0)
            # Animations with keyframes to ensure consistent brightness
            # At midpoint (50%), both images will be at 65% opacity (sum = 1.3)
            # This prevents the brightness dip that occurs when both are at 50% (sum = 1.0)
            fade_out = QPropertyAnimation(out_op_effect, b"opacity")
            fade_out.setDuration(fade_duration)
            fade_out.setStartValue(1.0)
            fade_out.setKeyValueAt(0.5, 0.65)  # 65% at midpoint to maintain brightness
            fade_out.setEndValue(0.0)
            fade_out.setEasingCurve(QEasingCurve.Linear)

            fade_in = QPropertyAnimation(in_op_effect, b"opacity")
            fade_in.setDuration(fade_duration)
            fade_in.setStartValue(0.0)
            fade_in.setKeyValueAt(0.5, 0.80)  # 65% at midpoint to maintain brightness
            fade_in.setEndValue(1.0)
            fade_in.setEasingCurve(QEasingCurve.Linear)

            def finish_fade():
                # Remove opacity and next label, keep main label only
                self.image_label.setPixmap(next_label.pixmap())
                self.image_label.original_pixmap = getattr(next_label, 'original_pixmap', None)
                self.image_label.resize(next_label.size())
                self.image_label.move(next_label.pos())
                self.image_label.setGraphicsEffect(None)
                next_label.hide()
                next_label.setGraphicsEffect(None)
                if hasattr(self, 'image_layout'):
                    self.image_layout.addWidget(next_label)
                self._current_slideshow_anim = None
                self._next_slideshow_anim = None
                self._current_opacity_anim = None
                self.highlight_image()
                self.main_window.image_display_manager.update_window_title_for_active_image()
            
            fade_in.finished.connect(finish_fade)
            # Store animations so not GC'd
            self._current_slideshow_anim = fade_out
            self._next_slideshow_anim = fade_in
            self._current_opacity_anim = fade_out

            fade_out.start()
            fade_in.start()
            return
        # End special 'none' direction

        # Continue as normal for left/right/top/bottom/random

        # Calculate rotation angles for animation
        current_angle, next_angle = self.calculate_slideshow_rotation_angles()

        if direction == 'random':
            direction = random.choice(['right', 'left', 'top', 'bottom'])

        if direction == 'right':
            # Next image starts completely off right edge, moves to center
            initial_pos = QPoint(container_size.width(), next_center_y)
            # Current image moves completely off left edge (use current image's actual size)
            current_size = self.image_label.size()
            final_current_pos = QPoint(-current_size.width(), self.image_label.y())
        elif direction == 'left':
            # Next image starts completely off left edge, moves to center
            initial_pos = QPoint(-next_label_size.width(), next_center_y)
            # Current image moves completely off right edge (use current image's actual size)
            current_size = self.image_label.size()
            final_current_pos = QPoint(container_size.width(), self.image_label.y())
        elif direction == 'top':
            # Next image starts completely off top edge, moves to center
            initial_pos = QPoint(next_center_x, -next_label_size.height())
            # Current image moves completely off bottom edge (use current image's actual size)
            current_size = self.image_label.size()
            final_current_pos = QPoint(self.image_label.x(), container_size.height())
        elif direction == 'bottom':
            # Next image starts completely off bottom edge, moves to center
            initial_pos = QPoint(next_center_x, container_size.height())
            # Current image moves completely off top edge (use current image's actual size)
            current_size = self.image_label.size()
            final_current_pos = QPoint(self.image_label.x(), -current_size.height())
        else:
            # Default to right
            initial_pos = QPoint(container_size.width(), next_center_y)
            current_size = self.image_label.size()
            final_current_pos = QPoint(-current_size.width(), self.image_label.y())

        # Set initial positions - ensure the incoming image is actually positioned off-screen
        next_label.move(initial_pos)
        next_label.show()  # Make sure it's visible at the off-screen position
        current_start_pos = self.image_label.pos()

        # Create position animations with easing based on overlap level
        # For negative delays, overlap is greater than 100% (incoming starts before outgoing)
        # Prevent division by zero by ensuring transition speed is at least 1ms
        safe_transition_speed = max(1, self.slideshow_transition_speed)
        current_overlap_percent = 100 - (self.slideshow_overlap_delay / safe_transition_speed * 100)
        use_linear_easing = current_overlap_percent < 30  # Use linear easing for low overlap

        current_anim = QPropertyAnimation(self.image_label, b"pos")
        current_anim.setDuration(safe_transition_speed)
        current_anim.setStartValue(current_start_pos)
        current_anim.setEndValue(final_current_pos)
        if use_linear_easing:
            current_anim.setEasingCurve(QEasingCurve.Linear)  # Constant speed for low overlap
        else:
            current_anim.setEasingCurve(QEasingCurve.InQuad)  # Outgoing: starts slow, predictable speedup

        next_anim = QPropertyAnimation(next_label, b"pos")
        next_anim.setDuration(safe_transition_speed)
        next_anim.setStartValue(initial_pos)
        next_anim.setEndValue(next_center_pos)
        if use_linear_easing:
            next_anim.setEasingCurve(QEasingCurve.Linear)  # Constant speed for low overlap
        else:
            next_anim.setEasingCurve(QEasingCurve.OutQuad)  # Incoming: starts fast, predictable slowdown

        # Create opacity animation for outgoing image fade-out using graphics effect
        # This approach works better on macOS than windowOpacity
        
        # Remove any existing graphics effects first
        self.image_label.setGraphicsEffect(None)
        
        # Create graphics opacity effect for the outgoing image
        opacity_effect = QGraphicsOpacityEffect(self.image_label)
        # Set initial opacity to 1.0 to prevent initial dimming
        opacity_effect.setOpacity(1.0)
        self.image_label.setGraphicsEffect(opacity_effect)
        
        # Create animation for the graphics effect opacity
        current_opacity_anim = QPropertyAnimation(opacity_effect, b"opacity")
        current_opacity_anim.setDuration(safe_transition_speed)
        
        # Set keyframes: stay at 1.0 until 60%, then fade to 0.0
        current_opacity_anim.setStartValue(1.0)  # Start fully opaque
        current_opacity_anim.setKeyValueAt(0.4, 1.0)  # Stay opaque until 60%
        current_opacity_anim.setEndValue(0.0)    # End fully transparent
        
        # Use InCubic easing curve for the fade-out portion
        current_opacity_anim.setEasingCurve(QEasingCurve.InCubic)
        
        # Create rotation animations if rotation is enabled
        current_rot_anim = None
        next_rot_anim = None
        current_rotation_target = None
        next_rotation_target = None
        
        if self.slideshow_max_rotation != 0:
            current_rot_anim, current_rotation_target = self.create_slideshow_rotation_animation(
                self.image_label, 0, current_angle)
            next_rot_anim, next_rotation_target = self.create_slideshow_rotation_animation(
                next_label, next_angle, 0)
        
        # Connect animation completion
        next_anim.finished.connect(self.slideshow_animation_finished)
        
        # Start animations with staggered timing to control overlap
        if self.slideshow_overlap_delay > 0:
            # Less overlap: Start outgoing animation first, delay incoming animation
            current_anim.start()
            current_opacity_anim.start()  # Start fade-out animation
            if current_rot_anim:
                current_rot_anim.start()
            
            # Limit delay to prevent long pauses - cap at 50% of transition time max
            max_reasonable_delay = safe_transition_speed * 0.5
            delay_ms = max(50, min(int(self.slideshow_overlap_delay), int(max_reasonable_delay)))
            
            def start_incoming_animation():
                if next_anim.state() == QPropertyAnimation.Stopped:  # Only start if not already started
                    next_anim.start()
                if next_rot_anim and next_rot_anim.state() == QPropertyAnimation.Stopped:
                    next_rot_anim.start()
            
            QTimer.singleShot(delay_ms, start_incoming_animation)
        elif self.slideshow_overlap_delay < 0:
            # Negative delay: Start incoming animation first, delay outgoing animation
            # This brings the incoming image into view sooner
            next_anim.start()
            if next_rot_anim:
                next_rot_anim.start()
            
            # Use absolute value of delay, but limit to prevent too much overlap
            max_reasonable_delay = safe_transition_speed * 0.3  # Allow up to 30% early start
            delay_ms = max(50, min(int(abs(self.slideshow_overlap_delay)), int(max_reasonable_delay)))
            
            def start_outgoing_animation():
                if current_anim.state() == QPropertyAnimation.Stopped:  # Only start if not already started
                    current_anim.start()
                if current_opacity_anim.state() == QPropertyAnimation.Stopped:  # Only start if not already started
                    current_opacity_anim.start()
                if current_rot_anim and current_rot_anim.state() == QPropertyAnimation.Stopped:
                    current_rot_anim.start()
            
            QTimer.singleShot(delay_ms, start_outgoing_animation)
        else:
            # Zero delay: Start both animations simultaneously
            current_anim.start()
            current_opacity_anim.start()  # Start fade-out animation
            next_anim.start()
            
            if current_rot_anim:
                current_rot_anim.start()
            if next_rot_anim:
                next_rot_anim.start()
        
        # Store animation references to prevent garbage collection
        self._current_slideshow_anim = current_anim
        self._next_slideshow_anim = next_anim
        self._current_rotation_anim = current_rot_anim
        self._next_rotation_anim = next_rot_anim
        self._current_opacity_anim = current_opacity_anim
        # Store rotation targets to prevent garbage collection
        self._current_rotation_target = current_rotation_target
        self._next_rotation_target = next_rotation_target

    def slideshow_animation_finished(self):
        """Handle completion of slideshow animation"""
        # The slideshow_next_label should now be at the exact final position and size
        # Copy its state to the main image_label, but recalculate center position
        # to ensure proper alignment (slideshow2 may have affected the position)
        
        # Get the final state from the next label
        next_pixmap = self.slideshow_next_label.pixmap()
        next_original = getattr(self.slideshow_next_label, 'original_pixmap', None)
        next_size = self.slideshow_next_label.size()
        
        if next_pixmap:
            # Copy the pixmap and original pixmap
            self.image_label.setPixmap(next_pixmap)
            if next_original:
                self.image_label.original_pixmap = next_original
            
            # Resize the label to match the pixmap size
            self.image_label.resize(next_size)
            
            # Recalculate center position to ensure proper alignment
            # This fixes the issue where images align to the right after slideshow2
            container_size = self.image_container.size()
            if container_size.width() < 100 or container_size.height() < 100:
                # Use effective display size to account for tree view and status bar
                if hasattr(self.window, 'get_effective_display_size'):
                    container_size = self.window.get_effective_display_size()
                else:
                    container_size = self.size()
            
            # Calculate centered position based on actual label size
            center_x = (container_size.width() - next_size.width()) // 2
            center_y = (container_size.height() - next_size.height()) // 2
            self.image_label.move(center_x, center_y)
        
        # Hide the next label and add it back to the layout
        self.slideshow_next_label.hide()
        if hasattr(self, 'image_layout'):
            self.image_layout.addWidget(self.slideshow_next_label)
        
        # Reset opacity of main image label and remove graphics effect
        self.image_label.setGraphicsEffect(None)
        
        # Clean up animation references
        self._current_slideshow_anim = None
        self._next_slideshow_anim = None
        self._current_rotation_anim = None
        self._next_rotation_anim = None
        self._current_opacity_anim = None
        self._current_rotation_target = None
        self._next_rotation_target = None
        
        # Now that animation is complete, safely update the thumbnail highlight
        # This was deferred from advance_slideshow() to avoid race conditions
        self.highlight_image()
        
        # Update window title to show the full path of the active image
        self.main_window.image_display_manager.update_window_title_for_active_image()

    # --------------------------------------------------
    # Slideshow rotation and animation helpers
    # --------------------------------------------------

    def calculate_slideshow_rotation_angles(self):
        """Calculate rotation angles for slideshow transitions (based on HTML version)"""
        if self.slideshow_max_rotation == 0:
            return 0, 0
        
        # Ensure minimum visible rotation (at least 5 degrees or 10% of max, whichever is larger)
        min_rotation = max(5, self.slideshow_max_rotation // 10)
        
        def get_random_angle():
            # Generate a random angle with better distribution
            # Use a more balanced approach that ensures visible rotation
            if random.random() < 0.7:  # 70% chance of full range rotation
                # Generate angle between min_rotation and max_rotation
                base_angle = random.randint(min_rotation, self.slideshow_max_rotation)
            else:  # 30% chance of moderate rotation (between min and 60% of max)
                moderate_max = max(min_rotation, int(self.slideshow_max_rotation * 0.6))
                base_angle = random.randint(min_rotation, moderate_max)
            
            # Ensure we don't get zero or very small angles
            if base_angle < min_rotation:
                base_angle = min_rotation
            
            return base_angle
        
        # Calculate angles - ensure both angles are significantly different from zero
        current_angle = get_random_angle()
        next_angle = get_random_angle()
        
        # Ensure angles are different enough to be visually distinct
        # If they're too similar, adjust one of them
        if abs(current_angle - next_angle) < min_rotation:
            if random.random() > 0.5:
                next_angle = current_angle + random.randint(min_rotation, min_rotation * 2)
            else:
                next_angle = current_angle - random.randint(min_rotation, min_rotation * 2)
        
        # Randomly make angles negative for more variety (but ensure they're still significant)
        if random.random() > 0.5:
            current_angle = -current_angle
        if random.random() > 0.5:
            next_angle = -next_angle
        
        # Final check: ensure both angles are at least the minimum rotation
        if abs(current_angle) < min_rotation:
            current_angle = min_rotation if current_angle >= 0 else -min_rotation
        if abs(next_angle) < min_rotation:
            next_angle = min_rotation if next_angle >= 0 else -min_rotation
        
        return current_angle, next_angle

    def create_slideshow_rotation_animation(self, label, start_angle, end_angle):
        """Create a rotation animation for a label during slideshow"""
        if start_angle == end_angle:
            return None
        
        # Create a custom QObject with a float property for rotation
        
        class RotationTarget(QObject):
            def __init__(self, parent=None):
                super().__init__(parent)
                self._value = 0.0
            
            def getValue(self):
                return self._value
            
            def setValue(self, value):
                self._value = value
                # Update rotation when value changes
                current_angle = start_angle + (end_angle - start_angle) * value
                self.update_label_rotation(current_angle)
            
            value = Property(float, getValue, setValue)
            
            def update_label_rotation(self, angle):
                """Update the label's rotation by transforming its original pixmap"""
                if not hasattr(label, 'original_pixmap') or label.original_pixmap is None:
                    return
                
                if abs(angle) < 0.1:  # Essentially no rotation
                    label.setPixmap(label.original_pixmap)
                else:
                    # Create rotated pixmap
                    transform = QTransform()
                    transform.rotate(angle)
                    rotated_pixmap = label.original_pixmap.transformed(transform, Qt.SmoothTransformation)
                    label.setPixmap(rotated_pixmap)
        
        # Create the target object
        target = RotationTarget(None)
        
        # Create the animation
        animation = QPropertyAnimation(target, b"value")
        animation.setDuration(self.slideshow_transition_speed)
        animation.setStartValue(0.0)
        animation.setEndValue(1.0)
        animation.setEasingCurve(QEasingCurve.InOutQuad)
        
        return animation, target

    # --------------------------------------------------
    # Slideshow speed and overlap controls
    # --------------------------------------------------

    def reset_to_slow_preset(self):
        """Reset slideshow to slow speed preset (3.5s slides, 2s transitions, 90° rotation, 100% overlap, direction random) - key 0"""
        self.slideshow_rate = 3500  # 3.5 seconds
        self.slideshow_transition_speed = 2000  # 2 seconds
        self.slideshow_max_rotation = 90  # 90° rotation
        self.slideshow_overlap_delay = 0  # 100% overlap (0 delay)
        self.slideshow_direction = 'random'  # default direction to random

        # Update timer interval if slideshow is running
        if self.window.current_view_mode == 'slideshow' and self.slideshow_timer.isActive():
            self.slideshow_timer.setInterval(self.slideshow_rate)
        
        # Save settings
        self.debounced_save_setting('slideshow_rate', self.slideshow_rate)
        self.debounced_save_setting('slideshow_transition_speed', self.slideshow_transition_speed)
        self.debounced_save_setting('slideshow_max_rotation', self.slideshow_max_rotation)
        self.debounced_save_setting('slideshow_overlap_delay', self.slideshow_overlap_delay)
        self.debounced_save_setting('slideshow_direction', self.slideshow_direction)

        if self.status_notification:
            self.status_notification.show_message(
                f"Slow preset: {self.slideshow_rate}ms slides, {self.slideshow_transition_speed}ms transitions, "
                f"{self.slideshow_max_rotation}° rotation, 100% overlap, direction: random"
            )

    def reset_to_fast_preset(self):
        """Reset slideshow to fast speed preset (3.5s slides, 1.2s transitions, 0° rotation, 100% overlap, direction none) - key 9"""
        self.slideshow_rate = 3500  # 3.5 seconds
        self.slideshow_transition_speed = 1200  # 1.2 seconds
        self.slideshow_max_rotation = 0  # 0° rotation
        self.slideshow_overlap_delay = 0  # 100% overlap
        self.slideshow_direction = 'none'  # default direction
        
        # Update timer interval if slideshow is running
        if self.window.current_view_mode == 'slideshow' and self.slideshow_timer.isActive():
            self.slideshow_timer.setInterval(self.slideshow_rate)
        
        # Save settings
        self.debounced_save_setting('slideshow_rate', self.slideshow_rate)
        self.debounced_save_setting('slideshow_transition_speed', self.slideshow_transition_speed)
        self.debounced_save_setting('slideshow_max_rotation', self.slideshow_max_rotation)
        self.debounced_save_setting('slideshow_overlap_delay', self.slideshow_overlap_delay)
        self.debounced_save_setting('slideshow_direction', self.slideshow_direction)

        if self.status_notification:
            self.status_notification.show_message(
                f"Fast preset: {self.slideshow_rate}ms slides, {self.slideshow_transition_speed}ms transitions, "
                f"{self.slideshow_max_rotation}° rotation, 100% overlap, direction: none"
            )

    def decrease_slideshow_overlap(self):
        """Decrease overlap between incoming and outgoing images (key 7)"""
        # Increase delay between animations - outgoing starts first, incoming delayed
        # Allow range from -30% to 100% overlap (negative means incoming starts first)
        self.slideshow_overlap_delay = min(self.slideshow_transition_speed * 1.0, 
                                         self.slideshow_overlap_delay + (self.slideshow_transition_speed * 0.1))
        
        self.debounced_save_setting('slideshow_overlap_delay', self.slideshow_overlap_delay)
        
        overlap_percent = 100 - (self.slideshow_overlap_delay / self.slideshow_transition_speed * 100)
        if self.status_notification:
            if overlap_percent > 100:
                self.status_notification.show_message(f"Overlap: {overlap_percent:.0f}% (incoming early)")
            else:
                self.status_notification.show_message(f"Overlap: {overlap_percent:.0f}% (less overlap)")

    def increase_slideshow_overlap(self):
        """Increase overlap between incoming and outgoing images (key 8)"""
        # Decrease delay between animations - both start closer together
        # Allow negative delays (incoming starts before outgoing)
        self.slideshow_overlap_delay = max(-self.slideshow_transition_speed * 0.3, 
                                         self.slideshow_overlap_delay - (self.slideshow_transition_speed * 0.1))
        
        self.debounced_save_setting('slideshow_overlap_delay', self.slideshow_overlap_delay)
        
        overlap_percent = 100 - (self.slideshow_overlap_delay / self.slideshow_transition_speed * 100)
        if self.status_notification:
            if overlap_percent > 100:
                self.status_notification.show_message(f"Overlap: {overlap_percent:.0f}% (incoming early)")
            else:
                self.status_notification.show_message(f"Overlap: {overlap_percent:.0f}% (more overlap)")

    # --------------------------------------------------
    # Slideshow keyboard event handling
    # --------------------------------------------------

    # Keyboard handling moved to keyboard_handler.py

    # --------------------------------------------------
    # Settings update methods
    # --------------------------------------------------
