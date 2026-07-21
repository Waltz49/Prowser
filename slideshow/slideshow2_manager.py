# Standard library imports
import os
import sys
import math
import random
import datetime
import traceback
from typing import List, Optional, Tuple

# Third-party imports
try:
    from PIL import Image, ImageEnhance
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

# PySide6 imports
from PySide6.QtCore import QTimer, QPoint, QPointF, QSize, Qt
from PySide6.QtGui import QPixmap, QKeyEvent
from PySide6.QtWidgets import QLabel, QWidget

# Local imports
import config

class Slideshow2Manager:
    """Encapsulates slideshow2 functionality, extracted from ImageBrowserWindow.
    Manages its own slideshow2 state and settings instead of proxying to the window.
    """

    def __init__(self, window):
        super().__setattr__('window', window)
        # Don't store debug_mode locally - always check window.debug_mode dynamically
        
        # Load slideshow2 settings from config (lazy load to allow profile directory to be set first)
        self.config = config.get_config()
        settings = self.config.load_settings()
        self.slideshow2_enlargement = settings.get('slideshow2_enlargement', 1.0)
        self.slideshow2_speed = settings.get('slideshow2_speed', 8)
        self.slideshow2_log_file = "/tmp/slideshow2.log"
        self.slideshow2_high_quality_scaling = settings.get('slideshow2_high_quality_scaling', True)
        
        # Initialize slideshow2 state attributes
        # Note: slideshow2 state is now tracked via window.current_view_mode == 'slideshow2'
        self.slideshow2_animation_timer = QTimer()
        self.slideshow2_animation_timer.timeout.connect(self.update_slideshow2_animation)
        self.slideshow2_current_path = None
        self.slideshow2_path_points = []
        self.slideshow2_current_point_index = 0
        self.slideshow2_animation_progress = 0.0
        self.slideshow2_current_x = 0
        self.slideshow2_current_y = 0
        self.slideshow2_path_direction = 1  # 1 for forward, -1 for backward

    def save_slideshow2_settings(self):
        """Save slideshow2 settings to config"""
        self.config.update_setting('slideshow2_enlargement', self.slideshow2_enlargement)
        self.config.update_setting('slideshow2_speed', self.slideshow2_speed)

    def update_slideshow2_settings(self, new_settings):
        """Update slideshow2 settings from settings dialog"""
        if 'slideshow2_enlargement' in new_settings:
            self.slideshow2_enlargement = new_settings['slideshow2_enlargement']
        
        if 'slideshow2_speed' in new_settings:
            self.slideshow2_speed = new_settings['slideshow2_speed']
        
        if 'slideshow2_high_quality_scaling' in new_settings:
            self.slideshow2_high_quality_scaling = new_settings['slideshow2_high_quality_scaling']

    # --------------------------------------------------
    # State management - using current_view_mode as source of truth
    # slideshow2_running property removed - use window.current_view_mode == 'slideshow2' directly
    # --------------------------------------------------
    
    # --------------------------------------------------
    # Generic attribute proxy helpers - restored for compatibility
    # --------------------------------------------------
    def __getattr__(self, name):
        return getattr(self.window, name)

    def __setattr__(self, name, value):
        if name == 'window':
            super().__setattr__(name, value)
        elif name in ['slideshow2_animation_timer',
                     'slideshow2_current_path', 'slideshow2_path_points', 'slideshow2_current_point_index',
                     'slideshow2_animation_progress', 'slideshow2_current_x', 'slideshow2_current_y',
                     'slideshow2_path_direction', 'slideshow2_enlargement', 'slideshow2_speed',
                     'slideshow2_log_file']:
            # These slideshow2 attributes are managed locally in the manager
            super().__setattr__(name, value)
        else:
            setattr(self.window, name, value)

    # --------------------------------------------------
    #  Original slideshow2 methods (verbatim, minor adjustments only
    #  to satisfy flake/pylint and avoid circular imports).
    # --------------------------------------------------
    #  The methods below were copied from image_browser_window.py and
    #  slightly re-indented.  They continue to use `self.` exactly as
    #  before, relying on the attribute-proxy above.

    # ---- Utility logging helpers ----
    def log_slideshow2(self, message: str):
        try:
            ts = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
            with open(self.slideshow2_log_file, 'a') as fh:
                fh.write(f'[{ts}] {message}\n')
        except Exception:  # pragma: no cover – logging must never fail
            traceback.print_exc()

    def high_quality_scale_pixmap(self, pixmap: QPixmap, target_width: int, target_height: int) -> QPixmap:
        """
        Scale a pixmap using high-quality PIL algorithms for better upscaling.
        Falls back to Qt.SmoothTransformation if PIL is not available or high-quality scaling is disabled.
        """
        # Check if high-quality scaling is enabled
        if not getattr(self, 'slideshow2_high_quality_scaling', True):
            self.log_slideshow2(f"Using Qt scaling: {pixmap.width()}x{pixmap.height()} -> {target_width}x{target_height}")
            return pixmap.scaled(
                target_width, target_height,
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation
            )
        
        if not PIL_AVAILABLE:
            # Fallback to Qt scaling
            self.log_slideshow2(f"PIL not available, using Qt scaling: {pixmap.width()}x{pixmap.height()} -> {target_width}x{target_height}")
            return pixmap.scaled(
                target_width, target_height,
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation
            )
        
        try:
            # Convert QPixmap to PIL Image
            qimage = pixmap.toImage()
            buffer = qimage.bits().asstring(qimage.sizeInBytes())
            
            # Create PIL Image from buffer
            pil_image = Image.frombytes(
                'RGBA' if qimage.hasAlphaChannel() else 'RGB',
                (qimage.width(), qimage.height()),
                buffer,
                'raw',
                'BGRA' if qimage.hasAlphaChannel() else 'BGR'
            )
            
            # Use high-quality resampling for upscaling
            if target_width > pixmap.width() or target_height > pixmap.height():
                # Upscaling - use LANCZOS for best quality
                resampling = Image.Resampling.LANCZOS
                algorithm = "LANCZOS (upscaling)"
            else:
                # Downscaling - use BICUBIC for good quality
                resampling = Image.Resampling.BICUBIC
                algorithm = "BICUBIC (downscaling)"
            
            self.log_slideshow2(f"Using PIL {algorithm}: {pixmap.width()}x{pixmap.height()} -> {target_width}x{target_height}")
            
            # Scale the image
            scaled_pil = pil_image.resize((target_width, target_height), resampling)
            
            # PIL→Qt after resize: prefer shared pil_to_qpixmap (RGB/RGBA, alpha policy for slideshow).
            # Historical path below used BGR/BGRA byte order to match QImage.Format_RGB888/RGBA8888;
            # kept as fallback if pil_to_qpixmap fails (e.g. buffer edge cases).
            from exif.exif_image_loader import pil_to_qpixmap

            px_shared = pil_to_qpixmap(
                scaled_pil, preserve_alpha=(scaled_pil.mode == "RGBA")
            )
            if px_shared is not None and not px_shared.isNull():
                return px_shared

            if scaled_pil.mode == 'RGBA':
                scaled_pil = scaled_pil.convert('BGRA')
                data = scaled_pil.tobytes('raw', 'BGRA')
            else:
                scaled_pil = scaled_pil.convert('BGR')
                data = scaled_pil.tobytes('raw', 'BGR')

            from PySide6.QtGui import QImage
            qimage_scaled = QImage(
                data,
                target_width,
                target_height,
                scaled_pil.width() * (4 if scaled_pil.mode == 'BGRA' else 3),
                QImage.Format.Format_RGBA8888 if scaled_pil.mode == 'BGRA' else QImage.Format.Format_RGB888
            )

            return QPixmap.fromImage(qimage_scaled)
            
        except Exception as e:
            self.log_slideshow2(f"High-quality scaling failed: {e}, falling back to Qt scaling")
            # Fallback to Qt scaling
            return pixmap.scaled(
                target_width, target_height,
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation
            )

    def init_path_tracking(self):
        try:
            with open('/tmp/points.txt', 'w') as fh:
                fh.write('# Slideshow2 path tracking\n')
                fh.write('# Format: TYPE,data...\n')
                fh.write('# IMAGESIZE,width,height\n')
                fh.write('# POINT,x,y\n')
                fh.write('# SPLINE_START,reason\n')
                fh.write('# CONTROL,x,y,index\n')
                fh.write('# SPLINE_END\n')
            self.log_slideshow2('Path tracking initialised')
        except Exception as exc:
            self.log_slideshow2(f'init_path_tracking error: {exc}')

    def log_spline_generation(self, reason, control_points):
        try:
            with open('/tmp/points.txt', 'a') as fh:
                fh.write(f'SPLINE_START,{reason}\n')
                for idx, pt in enumerate(control_points):
                    fh.write(f'CONTROL,{pt.x()},{pt.y()},{idx}\n')
                fh.write('SPLINE_END\n')
        except Exception as exc:
            self.log_slideshow2(f'log_spline_generation error: {exc}')

    def log_image_size_for_tracking(self, image_size):
        try:
            with open('/tmp/points.txt', 'a') as fh:
                fh.write(f'IMAGESIZE,{image_size.width()},{image_size.height()}\n')
        except Exception as exc:
            self.log_slideshow2(f'log_image_size_for_tracking error: {exc}')

    def log_viewport_center(self, viewport_x: int, viewport_y: int, container_size):
        try:
            cx = -viewport_x + container_size.width() // 2
            cy = -viewport_y + container_size.height() // 2
            with open('/tmp/points.txt', 'a') as fh:
                fh.write(f'POINT,{cx},{cy}\n')
        except Exception as exc:
            self.log_slideshow2(f'log_viewport_center error: {exc}')

    # ---- High-level control ----
    def toggle_slideshow2(self):
        displayed = self.get_displayed_images() or []
        if not displayed:
            self.log_slideshow2('No images loaded')
            return
        
        
        # If other slideshows are running, stop them first
        if hasattr(self.window, 'slideshow_manager') and self.window.current_view_mode == 'slideshow':
            self.log_slideshow2('Stopping regular slideshow first')
            self.window.slideshow_manager.stop_slideshow()
        if hasattr(self.window, 'slideshow3_manager') and self.window.current_view_mode == 'slideshow3':
            self.log_slideshow2('Stopping frames slideshow first')
            self.window.slideshow3_manager.stop_slideshow3()
        
        (self.stop_slideshow2 if self.window.current_view_mode == 'slideshow2' else self.start_slideshow2)()

    def start_slideshow2(self):
        from PySide6.QtCore import QTimer, QPoint
        # If other slideshows are running, stop them first
        if hasattr(self.window, 'slideshow_manager') and self.window.current_view_mode == 'slideshow':
            self.log_slideshow2('Stopping regular slideshow first')
            self.window.slideshow_manager.stop_slideshow()
        if hasattr(self.window, 'slideshow3_manager') and self.window.current_view_mode == 'slideshow3':
            self.log_slideshow2('Stopping frames slideshow first')
            self.window.slideshow3_manager.stop_slideshow3()
        
        displayed = self.get_displayed_images() or []
        if not displayed:
            self.log_slideshow2('No images to show')
            return
        self.window.current_view_mode = 'slideshow2'  # Set on main window for keyboard handler
        self.log_slideshow2(f'Set current_view_mode to slideshow2 on main_window')
        
        self.window.right_sidebar.hide_image_info_overlay()
        self.window.update_number_overlay()
        
        # Manage sidebar visibility for slideshow2 mode
        self.window.manage_sidebar_visibility_for_view_mode('slideshow2')
        
        # Hide status bar for slideshow2 mode
        if hasattr(self.window, 'status_bar') and self.window.status_bar.isVisible():
            self.window.status_bar.hide()
        
        # Update status bar sections for slideshow2 mode
        if hasattr(self.window, 'update_status_bar_sections'):
            self.window.update_status_bar_sections()
        
        # Update menu states to ensure shortcuts are properly enabled/disabled
        if hasattr(self.window, 'menu_manager'):
            self.window.menu_manager.update_view_menu_enabled_states()
            self.window.menu_manager.update_edit_menu_states()
            self.window.menu_manager.update_tools_menu_states()
            self.window.menu_manager.update_search_menu_states()
        
        # Initialize and start cursor manager for slideshow2 mode
        self.window.view_manager._setup_cursor_manager()
        
        self.log_slideshow2(f'Starting slideshow2: running={self.window.current_view_mode == "slideshow2"}, index={self.highlight_index}')
        
        # Set a flag to prevent main window from interfering with slideshow2
        self.image_label.slideshow2_active = True
            
        if self.window.debug_mode:
            self.init_path_tracking()
        self.slideshow2_current_velocity = QPoint(0, 0)
        self.slideshow2_last_position = None
        
        # Remove image label from layout to allow free positioning
        if self.image_label:
            # Remove from layout but keep as child of container
            if self.image_label.parent():
                self.image_label.setParent(None)
            self.image_label.setParent(self.image_container)
            
            # Ensure the image label is visible and properly positioned
            self.image_label.show()
            self.image_label.raise_()
            
            # Set initial position to center
            container_size = self._get_container_size()
            if container_size:
                self.image_label.move(0, 0)  # Will be positioned properly when image is loaded
        
        self.stacked_widget.setCurrentIndex(1)
        
        # Set browse view widget background to black for slideshow2 mode
        if getattr(self, 'stacked_widget', None) and self.stacked_widget.count() > 1:
            browse_view_widget = self.stacked_widget.widget(1)
            if browse_view_widget:
                browse_view_widget.setStyleSheet("""
                    QWidget {
                        background-color: rgb(0, 0, 0);
                        color: white;
                    }
                """)
        
        QTimer.singleShot(10, self.setup_slideshow2_layout)
        if self.status_notification:
            self.status_notification.show_message(
                f'Slideshow2 started - {self.slideshow2_speed}px/s, {self.slideshow2_enlargement:.1f}x')

    def setup_slideshow2_layout(self):
        # Check if slideshow2 is still running before starting animation timer
        if self.window.current_view_mode != 'slideshow2':
            self.log_slideshow2('Slideshow2 stopped before layout setup - skipping animation timer start')
            return
            
        self.stacked_widget.widget(1).updateGeometry()
        displayed = self.get_displayed_images() or []
        # Fallback to direct mapping
        if 0 <= self.highlight_index < len(displayed):
            img_path = displayed[self.highlight_index]
            self.show_slideshow2_image(img_path, self.highlight_index)
        self.slideshow2_animation_timer.start(16)  # ~60 FPS
        self.log_slideshow2(f'Slideshow2 timer started: running={self.window.current_view_mode == "slideshow2"}')

    def stop_slideshow2(self, target_mode='thumbnail'):
        from PySide6.QtCore import QPoint
        if self.window.current_view_mode != 'slideshow2':
            self.log_slideshow2(f'stop_slideshow2 called but current_view_mode is {self.window.current_view_mode} (target_mode={target_mode})')
            return
        
        self.log_slideshow2(f'stop_slideshow2 called with target_mode={target_mode}')
        self.log_slideshow2(f'Before stop: animation_timer_active={self.slideshow2_animation_timer.isActive()}')
        
        # Stop animation timer to prevent race conditions
        self.slideshow2_animation_timer.stop()
        
        self.log_slideshow2(f'After stop: animation_timer_active={self.slideshow2_animation_timer.isActive()}')
        
        # Clear the slideshow2 flag to allow normal image display
        self.image_label.slideshow2_active = False
        
        # Reset all image layers to default sizes, locations and angles
        self._reset_all_slideshow2_state(target_mode=target_mode)
        
        # Restore stacked widget to its initial state (background color, layout, etc.)
        self._restore_stacked_widget_to_initial_state()
        
        # Restore status bar visibility based on config setting (always restore when stopping slideshow2)
        if hasattr(self.window, 'status_bar'):
            settings = self.config.load_settings()
            status_bar_visible = settings.get('status_bar_visible', True)
            if status_bar_visible:
                self.window.status_bar.show()
            else:
                self.window.status_bar.hide()
        
        # Only change view mode and UI if going to thumbnail, otherwise let the caller handle it
        if target_mode == 'thumbnail':
            self.window.current_view_mode = 'thumbnail'  # Set on main window for keyboard handler
            self.stacked_widget.setCurrentIndex(0)  # Switch back to thumbnail view
            
            # Restore sidebar when returning to thumbnail mode
            self.window.manage_sidebar_visibility_for_view_mode('thumbnail')
            
            # Update status bar sections for thumbnail mode
            if hasattr(self.window, 'update_status_bar_sections'):
                self.window.update_status_bar_sections()
            
            # Prime and enable menu keys for view change
            if hasattr(self.window, 'menu_manager'):
                self.window.menu_manager.prime_menu_keys_for_view_change()
            
            # Don't call update_image_display() here as it interferes with slideshow2
            # highlight_index is already correct, just ensure it's visible
            self.ensure_highlighted_visible()
            
            # Efficiently refresh directory to show any added/removed files
            QTimer.singleShot(100, self.window.efficient_directory_refresh)
            
            # Clean up cursor manager
            if hasattr(self.window, 'cursor_manager') and self.window.cursor_manager:
                self.window.cursor_manager.cleanup()
                self.window.cursor_manager = None
        
        self.log_slideshow2(f'Slideshow2 stopped - all image layers reset to defaults (target: {target_mode})')

    def _reset_all_slideshow2_state(self, target_mode='thumbnail'):
        """Reset all image layers to default sizes, locations, angles and reload images"""
        try:
            # Reset image label to its default fullscreen state
            if self.image_label is not None:
                # Clear any custom pixmaps or transformations from slideshow2 FIRST
                self.image_label.clear()
                if hasattr(self.image_label, 'original_pixmap'):
                    delattr(self.image_label, 'original_pixmap')
                
                # Remove any graphics effects (rotations, etc.)
                self.image_label.setGraphicsEffect(None)
                
                # Force reset image container and label to screen size
                # This is critical - slideshow2 enlarges image_label which affects _get_effective_display_size()
                self._force_reset_container_and_label_sizes()
                
                # Don't call reset_image_label_for_fullscreen() during slideshow2 operation
                # as it resets the scale factor which we need for slideshow2
            
            # Clear the current pixmap to force fresh loading from original image file
            # This is critical - slideshow2 stores enlarged pixmaps in current_pixmap
            # which then get reused by subsequent modes causing the enlargement issue
            self.current_pixmap = None
            
            # Reset all slideshow2 tracking variables to defaults
            self.slideshow2_current_x = 0
            self.slideshow2_current_y = 0
            self.slideshow2_current_distance = 0.0
            self.slideshow2_path_direction = 1
            self.slideshow2_current_path = None
            
            # Clear path and spline data
            self.slideshow2_path_points = []
            self.slideshow2_current_point_index = 0
            if hasattr(self, 'slideshow2_control_points'):
                self.slideshow2_control_points = []
            if hasattr(self, 'slideshow2_spline_arc_lengths'):
                self.slideshow2_spline_arc_lengths = []
            if hasattr(self, 'slideshow2_spline_total_length'):
                self.slideshow2_spline_total_length = 0.0
            if hasattr(self, 'slideshow2_path_total_length'):
                self.slideshow2_path_total_length = 0.0
                
            # Reset velocity tracking
            if hasattr(self, 'slideshow2_current_velocity'):
                self.slideshow2_current_velocity = QPoint(0, 0)
            if hasattr(self, 'slideshow2_last_position'):
                self.slideshow2_last_position = None
            
            # Reset any animation progress
            self.slideshow2_animation_progress = 0.0
            
            # Don't reset scale factors during slideshow2 operation - preserve the enlargement
            # self.scale_factor = 1.0  # This was resetting the slideshow2 scaling
            # self.scroll_x = 0
            # self.scroll_y = 0
            
            # Ensure actual size mode is disabled - slideshow2 may have affected this
            self.is_actual_size = False
            
            # Clear any pan offsets
            if hasattr(self, 'pan_offset_x'):
                self.pan_offset_x = 0
            if hasattr(self, 'pan_offset_y'):
                self.pan_offset_y = 0
            
            # Clear any cached enlarged images to prevent reuse
            # Slideshow2 may have cached enlarged versions that we don't want to persist
            if self.cache_manager and self.current_image_path:
                # Clear the specific image from fullimage cache to force fresh loading
                try:
                    self.cache_manager.clear_cache_for_file(self.current_image_path)
                    self.log_slideshow2(f'Cleared cached enlarged image: {self.current_image_path}')
                except Exception as e:
                    self.log_slideshow2(f'Warning: Could not clear cache for {self.current_image_path}: {e}')
            
            # Reload the current image at default size if we have one
            displayed = self.get_displayed_images() or []
            if (getattr(self, 'current_image_path', None) and 
                displayed):
                # Force a complete reload of the current image at default size
                self._reload_current_image_at_default_size(target_mode)
            
            # Force update the display with the reset state to ensure proper sizing
            # This is critical to apply all the resets we just made for ALL target modes
            # Don't call update_image_display() here as it interferes with slideshow2
            
            self.log_slideshow2('All slideshow2 state variables and image transformations reset to defaults')
            
        except Exception as e:
            self.log_slideshow2(f'Error resetting slideshow2 state: {e}')
    
    def _reload_current_image_at_default_size(self, target_mode='thumbnail'):
        """Reload the current image at its default display size and position"""
        try:
            if not self.current_image_path:
                return
            
            # Only reload image if we're going back to thumbnail mode
            # If transitioning to browse mode, let the browse mode handle image loading
            if target_mode != 'thumbnail':
                self.log_slideshow2('Skipping image reload - transitioning to browse mode')
                return
                
            # Clear the image label first to remove slideshow2 transformations
            self.image_label.clear()
            
            # Ensure current_pixmap is cleared so we load fresh from file
            self.current_pixmap = None
            
            # Load the original image fresh from file (not cache) at normal size with EXIF correction
            try:
                from slideshow.slideshow_image_loader import load_slideshow_pixmap
                # Get ignore_exif_rotation from window (cached) instead of loading config every time
                ignore_exif = getattr(self.window, 'ignore_exif_rotation', False)
                pixmap = load_slideshow_pixmap(str(self.current_image_path), ignore_exif=ignore_exif)
            except ImportError:
                # Fallback to direct loading if exif_image_loader not available
                pixmap = QPixmap(str(self.current_image_path))
            
            if pixmap.isNull():
                self.log_slideshow2(f"Failed to reload image at default size: {self.current_image_path}")
                return
            
            # Store the fresh pixmap as current_pixmap for normal operation
            self.current_pixmap = pixmap
            
            # Get the container size for proper scaling
            container_size = self._get_effective_display_size()
            
            # Scale the image to fit the container properly (normal fullscreen behavior)
            scaled_pixmap = pixmap.scaled(
                container_size,
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation
            )
            
            # Set the scaled pixmap
            self.image_label.setPixmap(scaled_pixmap)
            
            # Center the image label
            self.window.browse_view_handler.center_image_label()
            
            self.log_slideshow2(f'Reloaded fresh image at default size: {scaled_pixmap.size()} (original: {pixmap.size()})')
            
        except Exception as e:
            self.log_slideshow2(f'Error reloading image at default size: {e}')

    def _force_reset_container_and_label_sizes(self):
        """Force reset image container and label to proper screen size (not slideshow2 enlarged size)"""
        try:
            # Get the effective display size to account for tree view and status bar
            screen_size = None
            
            # Use effective display size from main window if available
            if hasattr(self.window, 'get_effective_display_size'):
                screen_size = self.window.get_effective_display_size()
                self.log_slideshow2(f'Got effective display size: {screen_size}')
            
            # Fallback to screen size from Qt
            if not screen_size and getattr(self, 'screen', None) and self.screen():
                screen_size = self.screen().size()
                self.log_slideshow2(f'Fallback to screen size from screen(): {screen_size}')
            
            # Fallback to window size if screen detection fails
            if not screen_size or screen_size.width() < 400:
                screen_size = self.size()
                self.log_slideshow2(f'Fallback to window size(): {screen_size}')
            
            # Final fallback to reasonable default
            if not screen_size or screen_size.width() < 400 or screen_size.height() < 300:
                screen_size = QSize(1920, 1080)  # Fallback to reasonable default
                self.log_slideshow2(f'Using fallback default size: {screen_size}')
            
            # Force reset image_container to screen size
            self.image_container.resize(screen_size)
            self.log_slideshow2(f'Force reset image_container to: {screen_size}')
            
            # Force reset image_label to screen size (clearing any enlarged size from slideshow2)
            if self.image_label:
                self.image_label.resize(screen_size)
                # Reset position to center
                self.image_label.move(0, 0)
                self.log_slideshow2(f'Force reset image_label to: {screen_size}')
            
            self.log_slideshow2(f'Container and label sizes force reset to screen size: {screen_size}')
            
        except Exception as e:
            self.log_slideshow2(f'Error force resetting container/label sizes: {e}')

    def _restore_stacked_widget_to_initial_state(self):
        """Restore stacked widget to its initial state as created in setup_browse_view"""
        try:
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
                    self.log_slideshow2('Restored browse view widget background to black')
            
            # Restore image_label to layout with original properties
            if self.image_label and hasattr(self, 'image_layout'):
                # Check if image_label is already in the layout
                layout = self.image_layout
                label_in_layout = False
                for i in range(layout.count()):
                    item = layout.itemAt(i)
                    if item and item.widget() == self.image_label:
                        label_in_layout = True
                        break
                
                # If not in layout, re-add it at the correct position
                # Layout structure: [stretch, image_label, slideshow_next_label, stretch]
                if not label_in_layout:
                    # Find slideshow_next_label position
                    next_label_index = -1
                    for i in range(layout.count()):
                        item = layout.itemAt(i)
                        if item and item.widget() == self.slideshow_next_label:
                            next_label_index = i
                            break
                    
                    if next_label_index >= 0:
                        # Insert image_label before slideshow_next_label
                        layout.insertWidget(next_label_index, self.image_label)
                    else:
                        # Fallback: find first stretch and insert after it
                        for i in range(layout.count()):
                            item = layout.itemAt(i)
                            if item and item.spacerItem() is not None:
                                layout.insertWidget(i + 1, self.image_label)
                                break
                        else:
                            # Last resort: just add it
                            layout.addWidget(self.image_label)
                    
                    self.log_slideshow2('Re-added image_label to layout')
                
                # Restore image_label properties to initial state
                from PySide6.QtCore import Qt
                self.image_label.setAlignment(Qt.AlignCenter)
                self.image_label.setMinimumSize(100, 100)
                self.image_label.setMaximumSize(16777215, 16777215)
                self.image_label.setScaledContents(False)
                self.image_label.setFocusPolicy(Qt.NoFocus)
                self.image_label.setAttribute(Qt.WA_TransparentForMouseEvents, False)
                self.image_label.setStyleSheet("background-color: transparent;")
                
                # Ensure image_label is visible
                self.image_label.show()
                
                # Force layout update
                layout.update()
                
                self.log_slideshow2('Restored image_label to layout with original properties')
            
            # Restore slideshow_next_label to initial state
            if getattr(self, 'slideshow_next_label', None):
                # Ensure it's hidden (initial state)
                self.slideshow_next_label.hide()
                
                # Restore original properties
                from PySide6.QtCore import Qt
                self.slideshow_next_label.setAlignment(Qt.AlignCenter)
                self.slideshow_next_label.setMinimumSize(100, 100)
                self.slideshow_next_label.setScaledContents(False)
                self.slideshow_next_label.setFocusPolicy(Qt.NoFocus)
                self.slideshow_next_label.setStyleSheet("background-color: transparent;")
                
                # Clear any pixmap or graphics effects
                self.slideshow_next_label.clear()
                self.slideshow_next_label.setGraphicsEffect(None)
                
                # Ensure it's in the layout (it should already be there, but verify)
                if hasattr(self, 'image_layout'):
                    layout = self.image_layout
                    next_label_in_layout = False
                    for i in range(layout.count()):
                        item = layout.itemAt(i)
                        if item and item.widget() == self.slideshow_next_label:
                            next_label_in_layout = True
                            break
                    
                    if not next_label_in_layout:
                        # Re-add to layout if somehow removed
                        layout.addWidget(self.slideshow_next_label)
                        self.log_slideshow2('Re-added slideshow_next_label to layout')
                
                # Reset size constraints - let layout manage it
                self.slideshow_next_label.setMaximumSize(16777215, 16777215)
                
                self.log_slideshow2('Restored slideshow_next_label to initial state')
            
        except Exception as e:
            self.log_slideshow2(f'Error restoring stacked widget to initial state: {e}')

    # ---- Heavy slideshow2 logic migrated from ImageBrowserWindow ----
    def show_slideshow2_image(self, image_path: str, index: int):
        """Display an image in slideshow2 mode with cinematic movement"""
        if not os.path.exists(image_path):
            self.log_slideshow2(f"Image not found: {image_path}")
            return
            
        self.current_image_path = image_path
        
        # Load the image with EXIF correction
        try:
            from slideshow.slideshow_image_loader import load_slideshow_pixmap
            from config import get_config
            config = get_config()
            settings = config.load_settings()
            ignore_exif = settings.get('ignore_exif_rotation', False)
            pixmap = load_slideshow_pixmap(image_path, ignore_exif=ignore_exif)
        except ImportError:
            # Fallback to direct loading if exif_image_loader not available
            pixmap = QPixmap(image_path)
        
        if pixmap.isNull():
            self.log_slideshow2(f"Failed to load image: {image_path}")
            return
            
        # Apply any transformations (rotation, flip, etc.)
        if hasattr(self, 'apply_transformations_to_pixmap'):
            pixmap = self.apply_transformations_to_pixmap(pixmap)
        
        # Store the original pixmap for slideshow2 operations
        self.image_label.original_pixmap = pixmap
        
        # Get container size for scaling calculations
        container_size = self._get_container_size()
        if not container_size or container_size.width() <= 0 or container_size.height() <= 0:
            self.log_slideshow2("Invalid container size")
            return
        
        # Calculate enlargement so the image extends ~50 % beyond each screen edge
        image_width = pixmap.width()
        image_height = pixmap.height()
        container_width = container_size.width()
        container_height = container_size.height()

        width_scale = (container_width * 1.5) / image_width
        height_scale = (container_height * 1.5) / image_height
        base_scale = max(width_scale, height_scale)
        
        # Ensure minimum scale for slideshow2 - image should be at least 1.5x container size
        min_scale = max(1.5 * container_width / image_width, 1.5 * container_height / image_height)
        target_scale = max(base_scale * self.slideshow2_enlargement, min_scale)
        
        # Scale the pixmap directly for slideshow2 (bypass main window scaling)
        enlarged_width = int(image_width * target_scale)
        enlarged_height = int(image_height * target_scale)
        enlarged_pixmap = self.high_quality_scale_pixmap(
            pixmap, enlarged_width, enlarged_height
        )
        
        # Log image size for path tracking visualization (debug mode only)
        if self.window.debug_mode:
            self.log_image_size_for_tracking(QSize(enlarged_width, enlarged_height))
        
        # Set the enlarged pixmap directly to the image label
        if self.image_label:
            self.image_label.setPixmap(enlarged_pixmap)
            
            # Resize the image label to match the pixmap size
            self.image_label.resize(enlarged_width, enlarged_height)
            
            # Position the image label at the center initially
            label_x = (container_width - enlarged_width) // 2
            label_y = (container_height - enlarged_height) // 2
            self.image_label.move(label_x, label_y)
            
            # Ensure the image label is visible and properly displayed
            self.image_label.show()
            self.image_label.raise_()
            self.image_label.repaint()
            
            # Store current position for animation
            self.slideshow2_current_x = label_x
            self.slideshow2_current_y = label_y
        
        # Generate cinematic movement path
        self.generate_spline_path(QSize(enlarged_width, enlarged_height), container_size)
        
        # Reset path state to start animation from beginning
        self._reset_path_state()
        
        # Log scaling details for debugging
        actual_width_ratio = enlarged_width / container_width
        actual_height_ratio = enlarged_height / container_height
        self.log_slideshow2(
            f"Loaded image: {os.path.basename(image_path)} at {self.slideshow2_enlargement:.1f}x "
            f"(width ratio: {actual_width_ratio:.2f}, height ratio: {actual_height_ratio:.2f})"
        )
        self.log_slideshow2(
            f"Scaling details: image={image_width}x{image_height}, container={container_width}x{container_height}, "
            f"base_scale={base_scale:.2f}, target_scale={target_scale:.2f}, enlarged={enlarged_width}x{enlarged_height}"
        )

    def _generate_cinematic_control_points(self, image_width, image_height, container_size, num_points=7, margin=100):
        import math
        import random
        
        # Calculate the range of movement available
        # When image is larger than container, we can move it around
        w_range = image_width - container_size.width()
        h_range = image_height - container_size.height()
        
        self.log_slideshow2(f"Movement ranges: w_range={w_range}, h_range={h_range}")
        self.log_slideshow2(f"Image size: {image_width}x{image_height}, Container size: {container_size.width()}x{container_size.height()}")
        
        # If image is smaller than container in both dimensions, center it
        if w_range <= 0 and h_range <= 0:
            self.log_slideshow2("Image smaller than container - centering only")
            center_x = (container_size.width() - image_width) // 2
            center_y = (container_size.height() - image_height) // 2
            # Generate points around the center position with minimal movement
            points = []
            for i in range(num_points):
                points.append(QPoint(center_x, center_y))
            return points
        
        # Image is larger than container - generate movement points
        self.log_slideshow2("Image larger than container - generating movement points")
        
        points = []
        min_dist = 50  # Minimum distance between points
        
        for i in range(num_points):
            tries = 0
            while tries < 20:
                # Generate random position within the movement range
                if w_range > 0:
                    x = random.randint(-w_range, 0)  # Negative range for movement
                else:
                    x = (container_size.width() - image_width) // 2  # Center if no horizontal movement
                    
                if h_range > 0:
                    y = random.randint(-h_range, 0)  # Negative range for movement
                else:
                    y = (container_size.height() - image_height) // 2  # Center if no vertical movement
                
                # Check distance from existing points
                too_close = False
                for p in points:
                    dist = math.hypot(x - p.x(), y - p.y())
                    if dist < min_dist:
                        too_close = True
                        break
                
                if not too_close:
                    points.append(QPoint(x, y))
                    self.log_slideshow2(f"Generated point {i}: ({x}, {y})")
                    break
                tries += 1
            
            # If we couldn't find a good point, just add a random one
            if tries >= 20:
                if w_range > 0:
                    x = random.randint(-w_range, 0)
                else:
                    x = (container_size.width() - image_width) // 2
                if h_range > 0:
                    y = random.randint(-h_range, 0)
                else:
                    y = (container_size.height() - image_height) // 2
                points.append(QPoint(x, y))
                self.log_slideshow2(f"Added fallback point {i}: ({x}, {y})")
        
        return points

    def generate_spline_path(self, image_size: QSize, container_size: QSize):
        """Generate a smooth Catmull-Rom spline path over the viewport."""
        points = self._generate_cinematic_control_points(image_size.width(), image_size.height(), container_size, num_points=7)
        while len(points) < 4:
            points.append(points[-1])
        if self.window.debug_mode:
            self.log_spline_generation("initial_path", points)
        self.slideshow2_control_points = points  # Store control points for true spline following
        # Precompute arc-length table for parameterization
        num_spline_points = 1000
        spline_points = []
        arc_lengths = [0.0]
        total_length = 0.0
        prev = None
        for i in range(num_spline_points):
            t = i / (num_spline_points - 1)
            pt = self._catmull_rom_eval(points, t)
            spline_points.append(pt)
            if prev is not None:
                seg_len = math.hypot(pt.x() - prev.x(), pt.y() - prev.y())
                total_length += seg_len
            arc_lengths.append(total_length)
            prev = pt
        self.slideshow2_spline_points = spline_points
        self.slideshow2_spline_arc_lengths = arc_lengths
        self.slideshow2_spline_total_length = total_length
        self.slideshow2_path_points = spline_points  # For compatibility with visualization
        self.slideshow2_path_arc_lengths = arc_lengths
        self.slideshow2_path_total_length = total_length
        self.log_slideshow2(
            f"Generated spline path with {len(spline_points)} points – {total_length:.1f}px"
        )

    def _catmull_rom_eval(self, points, t):
        # t in [0, 1] over the whole spline
        n = len(points) - 1
        seg = t * n
        idx = int(seg)
        local_t = seg - idx
        # Clamp indices
        i0 = max(0, idx - 1)
        i1 = idx
        i2 = min(n, idx + 1)
        i3 = min(n, idx + 2)
        p0 = points[i0]
        p1 = points[i1]
        p2 = points[i2]
        p3 = points[i3]
        t2 = local_t * local_t
        t3 = t2 * local_t
        x = (
            (-0.5 * t3 + t2 - 0.5 * local_t) * p0.x()
            + (1.5 * t3 - 2.5 * t2 + 1) * p1.x()
            + (-1.5 * t3 + 2 * t2 + 0.5 * local_t) * p2.x()
            + (0.5 * t3 - 0.5 * t2) * p3.x()
        )
        y = (
            (-0.5 * t3 + t2 - 0.5 * local_t) * p0.y()
            + (1.5 * t3 - 2.5 * t2 + 1) * p1.y()
            + (-1.5 * t3 + 2 * t2 + 0.5 * local_t) * p2.y()
            + (0.5 * t3 - 0.5 * t2) * p3.y()
        )
        return QPointF(x, y)

    # --- Directional helpers (left/right/up/down) --------------------
    def _get_container_size(self):
        # Use effective display size to account for tree view and status bar
        if hasattr(self.window, 'get_effective_display_size'):
            container_size = self.window.get_effective_display_size()
        else:
            # Fallback to image_container size
            container_size = self.image_container.size()
            if container_size.width() < 100 or container_size.height() < 100:
                container_size = self.size()
        return container_size

    def _reset_path_state(self):
        self.slideshow2_current_distance = 0.0
        self.slideshow2_path_direction = 1

    def update_slideshow2_animation(self):
        """Move the image along the pre-computed spline with constant speed (arc-length parameterized)."""
        self.log_slideshow2("Animation update called")
        
        # Multiple safety checks to prevent animation from continuing after stop
        if (self.window.current_view_mode != 'slideshow2' or 
            not self.slideshow2_path_points):
            self.log_slideshow2(f"Animation update skipped: running={self.window.current_view_mode == 'slideshow2'}, path_points={len(self.slideshow2_path_points) if hasattr(self, 'slideshow2_path_points') else 0}")
            return
        
        # Additional safety check: if timer is not active, stop immediately
        if not self.slideshow2_animation_timer.isActive():
            self.log_slideshow2("Animation update skipped: timer not active")
            return
        speed_pps = self.slideshow2_speed
        px_per_frame = speed_pps / 60.0  # Assume ~60 FPS

        if not hasattr(self, 'slideshow2_current_distance'):
            self.slideshow2_current_distance = 0.0


        total_length = getattr(self, 'slideshow2_path_total_length', 0.0)
        if total_length == 0.0:
            return

        if self.slideshow2_path_direction == 1:
            self.slideshow2_current_distance += px_per_frame
            if self.slideshow2_current_distance >= total_length:
                self.slideshow2_current_distance = total_length
                self.slideshow2_path_direction = -1
        else:
            self.slideshow2_current_distance -= px_per_frame
            if self.slideshow2_current_distance <= 0.0:
                self.slideshow2_current_distance = 0.0
                self.slideshow2_path_direction = 1

        # Find the exact position along the spline curve using Catmull-Rom interpolation
        # instead of linear interpolation between adjacent points
        position = self._get_position_along_spline_curve(self.slideshow2_current_distance)
        
        # Ensure the image label has a pixmap before moving it
        if self.image_label:
                        # Check if the image label has a pixmap, if not, reload it
            if self.image_label.pixmap().isNull():
                self.log_slideshow2("Image label pixmap is null, reloading image")
                if getattr(self, 'current_image_path', None):
                    # Get actual index from highlight_index
                    if getattr(self, 'image_indices', None) and 0 <= self.highlight_index < len(self.image_indices):
                        actual_index = self.image_indices[self.highlight_index]
                        self.show_slideshow2_image(self.current_image_path, actual_index)
                    else:
                        self.show_slideshow2_image(self.current_image_path, self.highlight_index)
                    return
            
            # Move the image label to the new position
            new_x = int(position.x())
            new_y = int(position.y())
            self.image_label.move(new_x, new_y)
            self.slideshow2_current_x = new_x
            self.slideshow2_current_y = new_y
            
            # Ensure the image label is visible and raised
            self.image_label.show()
            self.image_label.raise_()
            
            # Debug logging to track what's happening
            if self.window.debug_mode:
                self.log_slideshow2(f"Animation update: pos=({new_x},{new_y}), pixmap_null={self.image_label.pixmap().isNull()}, visible={self.image_label.isVisible()}")
                self.log_viewport_center(new_x, new_y, self._get_container_size())

    def _get_position_along_spline_curve(self, target_distance):
        """Get the exact position along the spline curve at the given arc length distance using Catmull-Rom and the original control points."""
        if not hasattr(self, 'slideshow2_control_points') or not self.slideshow2_spline_arc_lengths:
            return QPoint(0, 0)
        arc = self.slideshow2_spline_arc_lengths
        total_length = self.slideshow2_spline_total_length
        if target_distance <= 0.0:
            t = 0.0
        elif target_distance >= total_length:
            t = 1.0
        else:
            # Binary search to find the segment
            lo, hi = 0, len(arc) - 1
            while lo < hi:
                mid = (lo + hi) // 2
                if arc[mid] < target_distance:
                    lo = mid + 1
                else:
                    hi = mid
            idx = max(1, min(lo, len(arc) - 1))
            d0 = arc[idx - 1]
            d1 = arc[idx]
            if d1 == d0:
                t_norm = 0.0
            else:
                t_norm = (target_distance - d0) / (d1 - d0)
            t = (idx - 1 + t_norm) / (len(arc) - 2)
        pt = self._catmull_rom_eval(self.slideshow2_control_points, t)
        return QPoint(int(pt.x()), int(pt.y()))

    def zoom_slideshow2_image(self, new_enlargement):
        """Zoom the slideshow2 image while preserving the center point of the viewport."""
        if self.window.current_view_mode != 'slideshow2' or not self.current_image_path:
            return
            
        # Get current state
        old_enlargement = self.slideshow2_enlargement
        container_size = self._get_container_size()
        
        self.log_slideshow2(f"Zooming slideshow2 from {old_enlargement:.1f}x to {new_enlargement:.1f}x")
        
        # Calculate current viewport center point in image coordinates
        current_label_pos = QPoint(self.slideshow2_current_x, self.slideshow2_current_y)
        viewport_center_x = -current_label_pos.x() + container_size.width() // 2
        viewport_center_y = -current_label_pos.y() + container_size.height() // 2
        
        # Load the original image with EXIF correction
        try:
            from slideshow.slideshow_image_loader import load_slideshow_pixmap
            from config import get_config
            config = get_config()
            settings = config.load_settings()
            ignore_exif = settings.get('ignore_exif_rotation', False)
            pixmap = load_slideshow_pixmap(str(self.current_image_path), ignore_exif=ignore_exif)
        except ImportError:
            # Fallback to direct loading if exif_image_loader not available
            pixmap = QPixmap(str(self.current_image_path))
        
        if pixmap.isNull():
            self.log_slideshow2(f"Failed to load image for zoom: {self.current_image_path}")
            return
            
        # Calculate new scale and dimensions
        image_width = pixmap.width()
        image_height = pixmap.height()
        container_width = container_size.width()
        container_height = container_size.height()
        
        width_scale = (container_width * 1.5) / image_width
        height_scale = (container_height * 1.5) / image_height
        base_scale = max(width_scale, height_scale)
        
        old_target_scale = base_scale * old_enlargement
        new_target_scale = base_scale * new_enlargement
        
        old_scaled_width = int(image_width * old_target_scale)
        old_scaled_height = int(image_height * old_target_scale)
        new_scaled_width = int(image_width * new_target_scale)
        new_scaled_height = int(image_height * new_target_scale)
        
        # Calculate the scale factor between old and new
        scale_ratio = new_target_scale / old_target_scale
        
        # Calculate new viewport center position in the scaled image
        new_center_x = viewport_center_x * scale_ratio
        new_center_y = viewport_center_y * scale_ratio
        
        # Calculate new image label position to maintain center point
        new_label_x = -(new_center_x - container_size.width() // 2)
        new_label_y = -(new_center_y - container_size.height() // 2)
        
        # Apply boundary constraints to prevent viewport from extending beyond image
        new_label_x, new_label_y = self._clamp_image_position(
            new_label_x, new_label_y, new_scaled_width, new_scaled_height, container_size
        )
        
        # Create and apply the new scaled pixmap
        new_scaled_pixmap = self.high_quality_scale_pixmap(
            pixmap, new_scaled_width, new_scaled_height
        )
        
        # Update the image
        self.image_label.resize(new_scaled_pixmap.size())
        self.image_label.setPixmap(new_scaled_pixmap)
        self.image_label.move(int(new_label_x), int(new_label_y))
        
        # Update position tracking
        self.slideshow2_current_x = int(new_label_x)
        self.slideshow2_current_y = int(new_label_y)
        
        # Update enlargement setting
        self.slideshow2_enlargement = new_enlargement
        self.config.update_setting('slideshow2_enlargement', self.slideshow2_enlargement)
        
        # Regenerate movement path for the new image size
        new_image_size = QSize(new_scaled_width, new_scaled_height)
        self.log_slideshow2(f"Regenerating movement path for new size: {new_scaled_width}x{new_scaled_height}")
        self.generate_spline_path(new_image_size, container_size)
        self._reset_path_state()
        
        # Show status notification
        if self.status_notification:
            self.status_notification.show_message(f"Slideshow2 zoom: {self.slideshow2_enlargement:.1f}x")
        
        # Log the zoom operation
        self.log_slideshow2(f"Zoomed from {old_enlargement:.1f}x to {new_enlargement:.1f}x - center preserved")

    def fit_slideshow2_image_to_canvas_width(self):
        """Scale image so its width matches the container (same base_scale as zoom); keep pan animation progress."""
        if self.window.current_view_mode != 'slideshow2' or not getattr(self, 'current_image_path', None):
            return

        old_total = float(getattr(self, 'slideshow2_spline_total_length', 0.0) or 0.0)
        old_dist = float(getattr(self, 'slideshow2_current_distance', 0.0) or 0.0)
        old_dir = int(getattr(self, 'slideshow2_path_direction', 1))
        frac = (old_dist / old_total) if old_total > 0 else 0.0

        image_path = str(self.current_image_path)
        if not os.path.exists(image_path):
            return

        try:
            from slideshow.slideshow_image_loader import load_slideshow_pixmap
            cfg = config.get_config()
            settings = cfg.load_settings()
            ignore_exif = settings.get('ignore_exif_rotation', False)
            pixmap = load_slideshow_pixmap(image_path, ignore_exif=ignore_exif)
        except ImportError:
            pixmap = QPixmap(image_path)

        if pixmap.isNull():
            return

        if hasattr(self, 'apply_transformations_to_pixmap'):
            pixmap = self.apply_transformations_to_pixmap(pixmap)

        container_size = self._get_container_size()
        if not container_size or container_size.width() < 1 or container_size.height() < 1:
            return

        image_width = pixmap.width()
        image_height = pixmap.height()
        if image_width < 1:
            return

        cw = container_size.width()
        ch = container_size.height()
        width_scale = (cw * 1.5) / image_width
        height_scale = (ch * 1.5) / image_height
        base_scale = max(width_scale, height_scale)
        if base_scale <= 0:
            return

        target_scale = cw / float(image_width)
        new_enlargement = target_scale / base_scale

        new_scaled_width = int(image_width * target_scale)
        new_scaled_height = int(image_height * target_scale)
        new_scaled_pixmap = self.high_quality_scale_pixmap(
            pixmap, new_scaled_width, new_scaled_height
        )
        actual_w = new_scaled_pixmap.width()
        actual_h = new_scaled_pixmap.height()

        if self.image_label:
            self.image_label.original_pixmap = pixmap
            self.image_label.resize(actual_w, actual_h)
            self.image_label.setPixmap(new_scaled_pixmap)

        self.slideshow2_enlargement = new_enlargement
        self.config.update_setting('slideshow2_enlargement', self.slideshow2_enlargement)

        self.generate_spline_path(QSize(actual_w, actual_h), container_size)
        new_total = float(getattr(self, 'slideshow2_spline_total_length', 0.0) or 0.0)
        if new_total > 0:
            self.slideshow2_current_distance = min(new_total, max(0.0, frac * new_total))
        else:
            self.slideshow2_current_distance = 0.0
        self.slideshow2_path_direction = old_dir

        if self.image_label and new_total > 0:
            position = self._get_position_along_spline_curve(self.slideshow2_current_distance)
            new_x = int(position.x())
            new_y = int(position.y())
            self.image_label.move(new_x, new_y)
            self.slideshow2_current_x = new_x
            self.slideshow2_current_y = new_y
            self.image_label.show()
            self.image_label.raise_()
            self.image_label.repaint()

        self.log_slideshow2(
            f"Fit canvas width: enlargement={new_enlargement:.3f}, scaled={actual_w}x{actual_h}, "
            f"arc_frac={frac:.3f}"
        )

    def _clamp_image_position(self, label_x, label_y, image_width, image_height, container_size):
        """Clamp image position to ensure viewport stays within image boundaries."""
        container_width = container_size.width()
        container_height = container_size.height()
        
        # If image is smaller than container, center it
        if image_width <= container_width:
            clamped_x = (container_width - image_width) // 2
        else:
            # If image is larger than container, clamp to prevent seeing beyond edges
            # Left edge: label_x should not be > 0 (image left edge visible)
            # Right edge: label_x should not be < container_width - image_width (image right edge visible)
            min_x = container_width - image_width  # Rightmost position (shows right edge)
            max_x = 0  # Leftmost position (shows left edge)
            clamped_x = max(min_x, min(max_x, label_x))
        
        # Same logic for Y axis
        if image_height <= container_height:
            clamped_y = (container_height - image_height) // 2
        else:
            # If image is larger than container, clamp to prevent seeing beyond edges
            min_y = container_height - image_height  # Bottom position (shows bottom edge)
            max_y = 0  # Top position (shows top edge)
            clamped_y = max(min_y, min(max_y, label_y))
        
        return clamped_x, clamped_y

    # Keyboard handling moved to keyboard_handler.py


