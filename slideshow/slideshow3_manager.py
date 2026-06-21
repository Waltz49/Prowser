#!/usr/bin/env python3
"""
Slideshow3 Manager - Frames Slideshow
Displays multiple images simultaneously floating across the screen in frames
"""

import random
import math
import time
from typing import List, Optional, Tuple
from dataclasses import dataclass

from PySide6.QtCore import (
    Qt, QTimer, QPropertyAnimation, QEasingCurve, QPoint, QPointF, QSize,
    Property, QObject, QRect
)
from PySide6.QtGui import QPixmap, QTransform, QPainter, QPen, QBrush, QColor, QLinearGradient
from PySide6.QtWidgets import QWidget, QLabel, QGraphicsOpacityEffect, QApplication

from config import get_config as _get_config


class CursorOverlayWidget(QWidget):
    """Invisible overlay widget to catch mouse events and manage cursor in slideshow3"""
    
    def __init__(self, parent=None, manager=None):
        super().__init__(parent)
        self.manager = manager
        # CRITICAL: Must NOT be transparent to mouse events - we need to catch them
        self.setAttribute(Qt.WA_TransparentForMouseEvents, False)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setAutoFillBackground(False)
        self.setStyleSheet("background-color: transparent;")
        # Accept mouse events
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.NoFocus)  # Don't steal keyboard focus
        
    def mouseMoveEvent(self, event):
        """Handle mouse movement"""
        if self.manager:
            self.manager._on_mouse_activity_overlay()
        # Don't call super() - we want to consume the event
    
    def mousePressEvent(self, event):
        """Handle mouse press"""
        if self.manager:
            self.manager._on_mouse_activity_overlay()
        # Don't call super() - we want to consume the event
    
    def mouseReleaseEvent(self, event):
        """Handle mouse release"""
        if self.manager:
            self.manager._on_mouse_activity_overlay()
        # Don't call super() - we want to consume the event
    
    def wheelEvent(self, event):
        """Handle wheel events"""
        if self.manager:
            self.manager._on_mouse_activity_overlay()
        # Don't call super() - we want to consume the event

class FrameWidget(QWidget):
    """Custom widget that displays a tilted frame with image"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.tilted_pixmap = None
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)

    def set_tilted_pixmap(self, pixmap):
        """Set the tilted pixmap (frame + image already rendered)"""
        # Clean up old pixmap before setting new one
        if self.tilted_pixmap and not self.tilted_pixmap.isNull():
            self.tilted_pixmap = None
        self.tilted_pixmap = pixmap
        self.update()

    def clear_pixmap(self):
        """Explicitly clear the pixmap to free memory"""
        if self.tilted_pixmap and not self.tilted_pixmap.isNull():
            self.tilted_pixmap = None

    def paintEvent(self, event):
        """Paint the tilted frame+image pixmap"""
        if not self.tilted_pixmap or self.tilted_pixmap.isNull():
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)

        # Center the tilted pixmap in the widget
        rect = self.rect()
        pixmap_rect = self.tilted_pixmap.rect()
        x = (rect.width() - pixmap_rect.width()) // 2
        y = (rect.height() - pixmap_rect.height()) // 2

        painter.drawPixmap(x, y, self.tilted_pixmap)

# ============================================================================
# Configuration Constants
# ============================================================================

# Maximum number of simultaneous frames
MAX_SIMULTANEOUS_FRAMES = 10

# Frame size range (as percentage of screen area)
FRAME_SIZE_MIN_PERCENT = 10
FRAME_SIZE_MAX_PERCENT = 30

# Speed range (seconds to cross screen) - slower for more visible movement
SPEED_MIN_SECONDS = 8
SPEED_MAX_SECONDS = 15

# Spline control points range (excluding start and end) - fewer points for more linear paths
SPLINE_CONTROL_POINTS_MIN = 1
SPLINE_CONTROL_POINTS_MAX = 2

# Animation frame rate (milliseconds)
ANIMATION_INTERVAL_MS = 16  # ~60 FPS

# Frame border width (pixels)
FRAME_BORDER_WIDTH = 8

# Frame border color (wood-like texture simulation)
FRAME_BORDER_COLOR = QColor(139, 90, 43)  # Brown wood color
FRAME_BORDER_DARK = QColor(101, 67, 33)  # Darker brown for depth
FRAME_BORDER_LIGHT = QColor(160, 120, 80)  # Lighter brown for highlight

# 3D tilt angle range (degrees)
TILT_ANGLE_MIN = -15
TILT_ANGLE_MAX = 15

# Extra 3D look ranges (in degrees) for simulated "perspective" rotations
TILT_X_MIN = -15    # -90 to 90 degrees
TILT_X_MAX = 15
TILT_Z_MIN = -15     # -90 to 90 degrees
TILT_Z_MAX = 15
TILT_RANGE_MAX = 45  # ±45 degrees from initial tilt
# Spawn rate parameters (milliseconds between spawn attempts)
SPAWN_INTERVAL_MIN_MS = 500
SPAWN_INTERVAL_MAX_MS = 2000

@dataclass
class FrameData:
    """Data structure for a single floating frame"""
    widget: QWidget
    image_label: QLabel
    start_pos: QPointF
    end_pos: QPointF
    control_points: List[QPointF]
    total_distance: float
    current_distance: float
    speed: float  # pixels per second
    size: QSize
    tilt_angle: float
    opacity_effect: QGraphicsOpacityEffect
    spawn_time: float  # Time when frame was spawned
    duration: float  # Total duration in seconds
    # New for 3D effect
    tilt_x: float = 0.0   # degrees X axis (current)
    tilt_z: float = 0.0   # degrees Z axis (current)
    initial_tilt_x: float = 0.0   # initial X axis tilt
    initial_tilt_z: float = 0.0   # initial Z axis tilt
    target_tilt_x: float = 0.0   # target X axis tilt
    target_tilt_z: float = 0.0   # target Z axis tilt
    original_pixmap: Optional[QPixmap] = None  # original pixmap before transformation
    # Fluttering parameters
    flutter_phase_x: float = 0.0  # Phase offset for X-axis flutter
    flutter_phase_z: float = 0.0  # Phase offset for Z-axis flutter
    flutter_frequency_x: float = 0.0  # Oscillation frequency for X-axis (Hz)
    flutter_frequency_z: float = 0.0  # Oscillation frequency for Z-axis (Hz)
    flutter_amplitude_x: float = 0.0  # Amplitude of X-axis flutter (degrees)
    flutter_amplitude_z: float = 0.0  # Amplitude of Z-axis flutter (degrees)

class Slideshow3Manager:
    """Manages Frames Slideshow functionality"""

    def __init__(self, window):
        """Initialize slideshow3 manager"""
        super().__setattr__('window', window)
        self.main_window = window
        self.config = _get_config()

        # Load settings from config
        settings = self.config.load_settings()

        # Configurable parameters (can be adjusted via keyboard)
        self.frame_size_min_percent = settings.get('slideshow3_frame_size_min_percent', FRAME_SIZE_MIN_PERCENT)
        self.frame_size_max_percent = settings.get('slideshow3_frame_size_max_percent', FRAME_SIZE_MAX_PERCENT)
        self.speed_min_seconds = settings.get('slideshow3_speed_min_seconds', SPEED_MIN_SECONDS)
        self.speed_max_seconds = settings.get('slideshow3_speed_max_seconds', SPEED_MAX_SECONDS)

        # Load max_simultaneous_frames from config (persisted by keyboard handler)
        self.max_simultaneous_frames = settings.get('slideshow3_max_simultaneous_frames', 30)

        self.active_frames: List[FrameData] = []
        self.animation_timer = QTimer()
        self.animation_timer.timeout.connect(self.update_animation)
        self.spawn_timer = QTimer()
        self.spawn_timer.timeout.connect(self.try_spawn_frame)
        self.displayed_images_cache: List[str] = []
        self.current_image_index = 0
        self.image_pool: List[str] = []  # Prerandomized list of images for frame assignment
        self.frames_container: Optional[QWidget] = None
        self.cursor_overlay: Optional[QWidget] = None
        # Dedicated cursor hiding timer for slideshow3
        self.cursor_hide_timer = QTimer()
        self.cursor_hide_timer.timeout.connect(self._check_cursor_hide)
        self.cursor_hide_interval_ms = 100  # Check every 100ms
        self.last_mouse_activity_time = 0.0
        self.mouse_activity_timeout_ms = 2000  # Hide after 2 seconds of inactivity
        self.cursor_is_hidden = False

    def __getattr__(self, name):
        """Proxy attributes to window"""
        return getattr(self.window, name)

    def __setattr__(self, name, value):
        """Proxy attributes to window except local ones"""
        if name == 'window':
            super().__setattr__(name, value)
        elif name in ['active_frames', 'animation_timer', 'spawn_timer',
                      'displayed_images_cache', 'current_image_index', 'image_pool',
                      'frames_container', 'cursor_overlay', 'main_window', 'config',
                      'frame_size_min_percent', 'frame_size_max_percent',
                      'speed_min_seconds', 'speed_max_seconds', 'max_simultaneous_frames',
                      'cursor_hide_timer', 'cursor_hide_interval_ms', 'last_mouse_activity_time',
                      'mouse_activity_timeout_ms', 'cursor_is_hidden']:
            super().__setattr__(name, value)
        else:
            setattr(self.window, name, value)

    def toggle_slideshow3(self):
        """Toggle frames slideshow mode"""
        displayed = self.get_displayed_images() if hasattr(self, 'get_displayed_images') else []
        if not displayed:
            return
        if hasattr(self.window, 'slideshow_manager') and self.window.current_view_mode == 'slideshow':
            self.window.slideshow_manager.stop_slideshow()
        if hasattr(self.window, 'slideshow2_manager') and self.window.current_view_mode == 'slideshow2':
            self.window.slideshow2_manager.stop_slideshow2()
        if self.window.current_view_mode == 'slideshow3':
            self.stop_slideshow3(target_mode='thumbnail')
        else:
            self.start_slideshow3()

    def get_effective_max_frames(self):
        """Get the effective maximum frames, capped by available unique images"""
        if not self.displayed_images_cache:
            return self.max_simultaneous_frames
        return min(self.max_simultaneous_frames, len(self.displayed_images_cache))

    def start_slideshow3(self):
        """Start frames slideshow mode"""
        # Determine which images to use for slideshow
        # If multiselect is active, use selected images; otherwise use displayed thumbnails
        if hasattr(self.window, 'multi_select_mode') and self.window.multi_select_mode:
            # Use selected images
            displayed = sorted(list(self.window.selected_files)) if hasattr(self.window, 'selected_files') else []
        else:
            # Use displayed thumbnails
            displayed = self.get_displayed_images() if hasattr(self, 'get_displayed_images') else []
        if not displayed:
            return
        if hasattr(self.window, 'slideshow_manager') and self.window.current_view_mode == 'slideshow':
            self.window.slideshow_manager.stop_slideshow()
        if hasattr(self.window, 'slideshow2_manager') and self.window.current_view_mode == 'slideshow2':
            self.window.slideshow2_manager.stop_slideshow2()
        self.window.current_view_mode = 'slideshow3'
        self.displayed_images_cache = displayed.copy()
        self.current_image_index = 0
        # Initialize prerandomized image pool
        self.image_pool = displayed.copy()
        random.shuffle(self.image_pool)
        self.window.right_sidebar.hide_image_info_overlay()
        self.window.update_number_overlay()
        self.window.manage_sidebar_visibility_for_view_mode('slideshow3')
        if hasattr(self.main_window, 'status_bar') and self.main_window.status_bar.isVisible():
            self.main_window.status_bar.hide()
        if hasattr(self.window, 'update_status_bar_sections'):
            self.window.update_status_bar_sections()
        if hasattr(self.main_window, 'menu_manager'):
            self.main_window.menu_manager.update_view_menu_enabled_states()
            self.main_window.menu_manager.update_edit_menu_states()
            self.main_window.menu_manager.update_tools_menu_states()
            self.main_window.menu_manager.update_search_menu_states()
        self.stacked_widget.setCurrentIndex(1)
        if getattr(self, 'stacked_widget', None) and self.stacked_widget.count() > 1:
            browse_view_widget = self.stacked_widget.widget(1)
            if browse_view_widget:
                browse_view_widget.setStyleSheet("""
                    QWidget {
                        background-color: rgb(0, 0, 0);
                        color: white;
                    }
                """)
        if getattr(self, 'image_label', None):
            self.image_label.hide()
        if getattr(self, 'slideshow_next_label', None):
            self.slideshow_next_label.hide()
        if getattr(self, 'image_container', None):
            self.image_container.hide()
        self._setup_frames_container()
        # Clean up regular cursor manager if it exists (we use slideshow3-specific system)
        if hasattr(self.main_window, 'cursor_manager') and self.main_window.cursor_manager:
            self.main_window.cursor_manager.cleanup()
            self.main_window.cursor_manager = None
        # Start slideshow3-specific cursor hiding system
        self._start_cursor_hiding()
        # Spawn some initial frames already on screen (simulating pre-travel)
        QTimer.singleShot(100, self._spawn_initial_frames)
        QTimer.singleShot(200, self._start_timers)
        if self.status_notification:
            self.status_notification.show_message("Frames slideshow started")

    def update_slideshow3_settings(self, new_settings):
        """Update slideshow3 settings from settings dialog"""
        if 'slideshow3_max_simultaneous_frames' in new_settings:
            self.max_simultaneous_frames = new_settings['slideshow3_max_simultaneous_frames']
            self.config.update_setting('slideshow3_max_simultaneous_frames', self.max_simultaneous_frames)
            self._enforce_max_frames()
        if 'slideshow3_frame_size_min_percent' in new_settings:
            self.frame_size_min_percent = new_settings['slideshow3_frame_size_min_percent']
        if 'slideshow3_frame_size_max_percent' in new_settings:
            self.frame_size_max_percent = new_settings['slideshow3_frame_size_max_percent']
        if 'slideshow3_speed_min_seconds' in new_settings:
            self.speed_min_seconds = new_settings['slideshow3_speed_min_seconds']
        if 'slideshow3_speed_max_seconds' in new_settings:
            self.speed_max_seconds = new_settings['slideshow3_speed_max_seconds']

    def _setup_frames_container(self):
        """Setup container widget for frames - uses full screen"""
        if not hasattr(self, 'stacked_widget') or self.stacked_widget.count() < 2:
            return
        browse_view_widget = self.stacked_widget.widget(1)
        if not browse_view_widget:
            return
        browse_size = browse_view_widget.size()
        if not self.frames_container:
            self.frames_container = QWidget(browse_view_widget)
            self.frames_container.setAttribute(Qt.WA_TransparentForMouseEvents, True)
            self.frames_container.setStyleSheet("background-color: transparent;")
            self.frames_container.setAttribute(Qt.WA_NoSystemBackground, True)
            self.frames_container.setAutoFillBackground(False)
        self.frames_container.setGeometry(0, 0, browse_size.width(), browse_size.height())
        self.frames_container.show()
        self.frames_container.raise_()
        
        # Create invisible cursor overlay widget to catch mouse events
        if not self.cursor_overlay:
            self.cursor_overlay = CursorOverlayWidget(browse_view_widget, manager=self)
        self.cursor_overlay.setGeometry(0, 0, browse_size.width(), browse_size.height())
        self.cursor_overlay.show()
        self.cursor_overlay.raise_()  # Put it on top of everything
        
        self.frames_container.update()
        self.frames_container.repaint()
        browse_view_widget.update()
        browse_view_widget.repaint()

    def _start_cursor_hiding(self):
        """Start cursor hiding system for slideshow3"""
        # Initialize mouse activity tracking
        self.last_mouse_activity_time = time.time()
        self.cursor_is_hidden = False
        # Start timer to check and hide cursor after inactivity
        self.cursor_hide_timer.start(self.cursor_hide_interval_ms)
    
    def _check_cursor_hide(self):
        """Check if cursor should be hidden based on inactivity"""
        if self.window.current_view_mode != 'slideshow3':
            return
        
        current_time = time.time()
        time_since_activity = (current_time - self.last_mouse_activity_time) * 1000  # Convert to ms
        
        if time_since_activity >= self.mouse_activity_timeout_ms:
            # Hide cursor if not already hidden
            if not self.cursor_is_hidden:
                self.main_window.setCursor(Qt.BlankCursor)
                app = QApplication.instance()
                if app:
                    app.setOverrideCursor(Qt.BlankCursor)
                self.cursor_is_hidden = True
    
    def _on_mouse_activity_overlay(self):
        """Called by overlay widget when mouse activity is detected"""
        self.last_mouse_activity_time = time.time()
        # Show cursor immediately - force it visible
        app = QApplication.instance()
        if app:
            app.restoreOverrideCursor()
        self.main_window.setCursor(Qt.ArrowCursor)
        self.cursor_is_hidden = False
    
    def _force_restore_cursor(self):
        """Force restore cursor - called after widget operations complete"""
        app = QApplication.instance()
        if app:
            # Clear all override cursors
            while app.overrideCursor():
                app.restoreOverrideCursor()
        self.main_window.setCursor(Qt.ArrowCursor)
        self.cursor_is_hidden = False
    
    def _start_timers(self):
        """Start animation and spawn timers"""
        self.animation_timer.start(ANIMATION_INTERVAL_MS)
        self.try_spawn_frame()
        self._schedule_next_spawn()

    def _get_next_image(self):
        """Get next image from prerandomized pool, refilling if empty"""
        if not self.image_pool:
            # Refill pool when empty
            if self.displayed_images_cache:
                self.image_pool = self.displayed_images_cache.copy()
                random.shuffle(self.image_pool)
            else:
                return None
        return self.image_pool.pop(0)
    
    def _schedule_next_spawn(self):
        """Schedule next frame spawn attempt"""
        if self.window.current_view_mode != 'slideshow3':
            return
        current_visible = len(self.active_frames)
        target_count = self.get_effective_max_frames()
        if current_visible < target_count * 0.5:
            interval = random.randint(SPAWN_INTERVAL_MIN_MS, SPAWN_INTERVAL_MAX_MS // 2)
        elif current_visible < target_count:
            interval = random.randint(SPAWN_INTERVAL_MIN_MS, SPAWN_INTERVAL_MAX_MS)
        else:
            interval = random.randint(SPAWN_INTERVAL_MAX_MS // 2, SPAWN_INTERVAL_MAX_MS)
        self.spawn_timer.setSingleShot(True)
        self.spawn_timer.start(interval)

    def try_spawn_frame(self):
        """Attempt to spawn a new frame if conditions are met"""
        if self.window.current_view_mode != 'slideshow3':
            return
        if not self.frames_container or not self.frames_container.isVisible():
            self._setup_frames_container()
            if not self.frames_container:
                self._schedule_next_spawn()
                return
        effective_max = self.get_effective_max_frames()
        if len(self.active_frames) >= effective_max:
            self._schedule_next_spawn()
            return
        current_count = len(self.active_frames)
        target_count = effective_max
        if current_count < target_count * 0.5:
            spawn_probability = 0.8
        elif current_count < target_count * 0.8:
            spawn_probability = 0.6
        else:
            spawn_probability = 0.4
        if random.random() < spawn_probability:
            self._spawn_frame()
        self._schedule_next_spawn()

    def _spawn_frame(self):
        """Spawn a new floating frame with 3D-like random rotation"""
        if not self.frames_container:
            return
        if not self.displayed_images_cache:
            return
        container_size = self.frames_container.size()
        if container_size.width() < 100 or container_size.height() < 100:
            if getattr(self, 'stacked_widget', None) and self.stacked_widget.count() > 1:
                browse_view_widget = self.stacked_widget.widget(1)
                if browse_view_widget:
                    container_size = browse_view_widget.size()
            if container_size.width() < 100 or container_size.height() < 100:
                if hasattr(self.window, 'get_effective_display_size'):
                    container_size = self.window.get_effective_display_size()
                else:
                    container_size = self.size()
        image_path = self._get_next_image()
        if not image_path:
            return
        try:
            from slideshow.slideshow_image_loader import load_slideshow_pixmap
            from config import get_config
            config = get_config()
            settings = config.load_settings()
            ignore_exif = settings.get('ignore_exif_rotation', False)
            pixmap = load_slideshow_pixmap(str(image_path), ignore_exif=ignore_exif)
        except ImportError:
            pixmap = QPixmap(str(image_path))
        if pixmap.isNull():
            return
        screen_area = container_size.width() * container_size.height()
        target_area = screen_area * random.uniform(self.frame_size_min_percent / 100.0, self.frame_size_max_percent / 100.0)
        aspect_ratio = pixmap.width() / pixmap.height()
        frame_height = int(math.sqrt(target_area / aspect_ratio))
        frame_width = int(frame_height * aspect_ratio)
        min_size = 100
        if frame_width < min_size or frame_height < min_size:
            if frame_width < frame_height:
                frame_width = min_size
                frame_height = int(min_size / aspect_ratio)
            else:
                frame_height = min_size
                frame_width = int(min_size * aspect_ratio)
        frame_size = QSize(frame_width, frame_height)
        border_total = FRAME_BORDER_WIDTH * 2
        image_size = QSize(frame_width - border_total, frame_height - border_total)
        # Use KeepAspectRatioByExpanding to ensure image fills the entire area and touches all frame edges
        # This eliminates gaps between image and frame border
        scaled_pixmap = pixmap.scaled(
            image_size,
            Qt.KeepAspectRatioByExpanding,
            Qt.SmoothTransformation
        )
        # Clean up original pixmap immediately after scaling - no longer needed
        pixmap = None
        
        # Choose random 3D "tilt" angles
        initial_tilt_x = random.uniform(TILT_X_MIN, TILT_X_MAX)  # vertical slant (simulate X axis)
        tilt_y = random.uniform(TILT_ANGLE_MIN, TILT_ANGLE_MAX)  # Y axis: classical tilt
        initial_tilt_z = random.uniform(TILT_Z_MIN, TILT_Z_MAX)  # slight "roll" left/right

        # Calculate target tilt values - vary up to ±20 degrees from initial
        target_tilt_x = initial_tilt_x + random.uniform(-TILT_RANGE_MAX, TILT_RANGE_MAX)
        target_tilt_x = max(TILT_X_MIN, min(TILT_X_MAX, target_tilt_x))  # Clamp to valid range
        target_tilt_z = initial_tilt_z + random.uniform(-TILT_RANGE_MAX, TILT_RANGE_MAX)
        target_tilt_z = max(TILT_Z_MIN, min(TILT_Z_MAX, target_tilt_z))  # Clamp to valid range

        # Initialize fluttering parameters for subtle cyclical motion (needed for size calculation)
        # Very subtle flutter - slow frequency and small amplitude
        flutter_freq_x = random.uniform(0.01, 0.02)  # Hz - flutter frequency for X-axis (very slow, subtle flutter)
        flutter_freq_z = random.uniform(0.01, 0.02)  # Hz - flutter frequency for Z-axis (very slow, subtle flutter)
        flutter_amp_x = random.uniform(1.0, 3.0)  # degrees - amplitude of X flutter (very subtle)
        flutter_amp_z = random.uniform(1.0, 3.0)  # degrees - amplitude of Z flutter (very subtle)
        flutter_phase_x = random.uniform(0, 2 * math.pi)  # Random phase offset
        flutter_phase_z = random.uniform(0, 2 * math.pi)  # Random phase offset

        # Compose the frame and image in 2D as before
        complete_pixmap = self._create_framed_image_pixmap(frame_size, scaled_pixmap, image_size)
        # Clean up scaled_pixmap immediately after creating complete_pixmap - no longer needed
        scaled_pixmap = None

        # Calculate maximum size needed to accommodate all possible tilts during animation including flutter
        max_tilted_size = self._calculate_max_tilted_size(
            complete_pixmap, tilt_y, initial_tilt_x, initial_tilt_z, target_tilt_x, target_tilt_z,
            flutter_amp_x, flutter_amp_z
        )
        widget_size = QSize(
            max(frame_width, max_tilted_size.width()),
            max(frame_height, max_tilted_size.height())
        )

        # Don't apply initial transform here - start with flat image and apply transforms dynamically
        # This ensures flutter and tilt are applied together to the flat image from the start
        frame_widget = FrameWidget(self.frames_container)
        frame_widget.setFixedSize(widget_size)
        # Start with flat pixmap - transforms will be applied in update_animation
        frame_widget.set_tilted_pixmap(complete_pixmap)

        image_label = QLabel(frame_widget)
        image_label.hide()  # Not used, kept for compatibility

        start_pos, end_pos, control_points, total_distance = self._generate_spline_path(
            container_size, widget_size
        )

        duration = random.uniform(self.speed_min_seconds, self.speed_max_seconds)
        speed = total_distance / duration  # pixels per second

        frame_widget.move(int(start_pos.x()), int(start_pos.y()))

        opacity_effect = QGraphicsOpacityEffect(frame_widget)
        frame_widget.setGraphicsEffect(opacity_effect)
        opacity_effect.setOpacity(0.0)

        frame_data_marker = {'_fading_in': False, '_entered_screen': False}
        
        # Flutter parameters already calculated above, use them here
        frame_data = FrameData(
            widget=frame_widget,
            image_label=image_label,
            start_pos=start_pos,
            end_pos=end_pos,
            control_points=control_points,
            total_distance=total_distance,
            current_distance=0.0,
            speed=speed,
            size=widget_size,
            tilt_angle=tilt_y,  # For backward compat
            opacity_effect=opacity_effect,
            spawn_time=time.time(),  # Track actual spawn time for flutter calculations
            duration=duration,
            tilt_x=initial_tilt_x,
            tilt_z=initial_tilt_z,
            initial_tilt_x=initial_tilt_x,
            initial_tilt_z=initial_tilt_z,
            target_tilt_x=target_tilt_x,
            target_tilt_z=target_tilt_z,
            original_pixmap=complete_pixmap,
            flutter_phase_x=flutter_phase_x,
            flutter_phase_z=flutter_phase_z,
            flutter_frequency_x=flutter_freq_x,
            flutter_frequency_z=flutter_freq_z,
            flutter_amplitude_x=flutter_amp_x,
            flutter_amplitude_z=flutter_amp_z,
        )
        # Add fade-in tracking attributes
        frame_data._fading_in = False
        frame_data._entered_screen = False

        # Apply initial transform with flutter to flat image immediately
        # This ensures flutter and tilt are applied together from the start
        elapsed_time = 0.0  # Just spawned, so elapsed time is 0
        flutter_x = (math.sin(2 * math.pi * frame_data.flutter_frequency_x * elapsed_time + frame_data.flutter_phase_x) * frame_data.flutter_amplitude_x +
                    math.sin(4 * math.pi * frame_data.flutter_frequency_x * elapsed_time + frame_data.flutter_phase_x * 1.3) * frame_data.flutter_amplitude_x * 0.15)  # Reduced harmonic for subtlety
        flutter_z = (math.sin(2 * math.pi * frame_data.flutter_frequency_z * elapsed_time + frame_data.flutter_phase_z) * frame_data.flutter_amplitude_z +
                    math.sin(4 * math.pi * frame_data.flutter_frequency_z * elapsed_time + frame_data.flutter_phase_z * 1.5) * frame_data.flutter_amplitude_z * 0.12)  # Reduced harmonic for subtlety
        initial_tilt_with_flutter_x = initial_tilt_x + flutter_x
        initial_tilt_with_flutter_z = initial_tilt_z + flutter_z
        initial_tilted_pixmap = self._apply_tilt_transform(
            complete_pixmap,
            initial_tilt_with_flutter_x,
            tilt_y,
            initial_tilt_with_flutter_z
        )
        frame_widget.set_tilted_pixmap(initial_tilted_pixmap)

        self.active_frames.append(frame_data)
        frame_widget.show()
        frame_widget.raise_()
        frame_widget.update()
        frame_widget.repaint()
        frame_widget.setAttribute(Qt.WA_NoSystemBackground, False)
        frame_widget.setAutoFillBackground(True)
        # Don't fade in immediately - wait for frame to enter screen

    def _spawn_frame_with_pretravel(self, progress_min=0.1, progress_max=0.9):
        """Spawn a frame that's already partway through its journey (for initial screen population)"""
        if not self.frames_container:
            return
        if not self.displayed_images_cache:
            return
        
        # Spawn a frame normally first
        container_size = self.frames_container.size()
        if container_size.width() < 100 or container_size.height() < 100:
            if getattr(self, 'stacked_widget', None) and self.stacked_widget.count() > 1:
                browse_view_widget = self.stacked_widget.widget(1)
                if browse_view_widget:
                    container_size = browse_view_widget.size()
            if container_size.width() < 100 or container_size.height() < 100:
                if hasattr(self.window, 'get_effective_display_size'):
                    container_size = self.window.get_effective_display_size()
                else:
                    container_size = self.size()
        image_path = self._get_next_image()
        if not image_path:
            return
        try:
            from slideshow.slideshow_image_loader import load_slideshow_pixmap
            from config import get_config
            config = get_config()
            settings = config.load_settings()
            ignore_exif = settings.get('ignore_exif_rotation', False)
            pixmap = load_slideshow_pixmap(str(image_path), ignore_exif=ignore_exif)
        except ImportError:
            pixmap = QPixmap(str(image_path))
        if pixmap.isNull():
            return
        screen_area = container_size.width() * container_size.height()
        target_area = screen_area * random.uniform(self.frame_size_min_percent / 100.0, self.frame_size_max_percent / 100.0)
        aspect_ratio = pixmap.width() / pixmap.height()
        frame_height = int(math.sqrt(target_area / aspect_ratio))
        frame_width = int(frame_height * aspect_ratio)
        min_size = 100
        if frame_width < min_size or frame_height < min_size:
            if frame_width < frame_height:
                frame_width = min_size
                frame_height = int(min_size / aspect_ratio)
            else:
                frame_height = min_size
                frame_width = int(min_size * aspect_ratio)
        frame_size = QSize(frame_width, frame_height)
        border_total = FRAME_BORDER_WIDTH * 2
        image_size = QSize(frame_width - border_total, frame_height - border_total)
        scaled_pixmap = pixmap.scaled(
            image_size,
            Qt.KeepAspectRatioByExpanding,
            Qt.SmoothTransformation
        )
        pixmap = None
        
        # Choose random 3D "tilt" angles
        initial_tilt_x = random.uniform(TILT_X_MIN, TILT_X_MAX)
        tilt_y = random.uniform(TILT_ANGLE_MIN, TILT_ANGLE_MAX)
        initial_tilt_z = random.uniform(TILT_Z_MIN, TILT_Z_MAX)

        # Calculate target tilt values
        target_tilt_x = initial_tilt_x + random.uniform(-TILT_RANGE_MAX, TILT_RANGE_MAX)
        target_tilt_x = max(TILT_X_MIN, min(TILT_X_MAX, target_tilt_x))
        target_tilt_z = initial_tilt_z + random.uniform(-TILT_RANGE_MAX, TILT_RANGE_MAX)
        target_tilt_z = max(TILT_Z_MIN, min(TILT_Z_MAX, target_tilt_z))

        # Initialize fluttering parameters for subtle cyclical motion (needed for size calculation)
        # Very subtle flutter - slow frequency and small amplitude
        flutter_freq_x = random.uniform(0.01, 0.02)  # Hz - flutter frequency for X-axis (very slow, subtle flutter)
        flutter_freq_z = random.uniform(0.01, 0.02)  # Hz - flutter frequency for Z-axis (very slow, subtle flutter)
        flutter_amp_x = random.uniform(1.0, 3.0)  # degrees - amplitude of X flutter (very subtle)
        flutter_amp_z = random.uniform(1.0, 3.0)  # degrees - amplitude of Z flutter (very subtle)
        flutter_phase_x = random.uniform(0, 2 * math.pi)  # Random phase offset
        flutter_phase_z = random.uniform(0, 2 * math.pi)  # Random phase offset

        # Compose the frame and image
        complete_pixmap = self._create_framed_image_pixmap(frame_size, scaled_pixmap, image_size)
        scaled_pixmap = None

        # Calculate maximum size needed including flutter
        max_tilted_size = self._calculate_max_tilted_size(
            complete_pixmap, tilt_y, initial_tilt_x, initial_tilt_z, target_tilt_x, target_tilt_z,
            flutter_amp_x, flutter_amp_z
        )
        widget_size = QSize(
            max(frame_width, max_tilted_size.width()),
            max(frame_height, max_tilted_size.height())
        )

        # Generate path
        start_pos, end_pos, control_points, total_distance = self._generate_spline_path(
            container_size, widget_size
        )

        duration = random.uniform(self.speed_min_seconds, self.speed_max_seconds)
        speed = total_distance / duration

        # Calculate pre-travel progress and position
        progress = random.uniform(progress_min, progress_max)
        current_distance = total_distance * progress
        current_pos = self._get_position_along_spline_from_points(start_pos, end_pos, control_points, total_distance, current_distance)

        # Interpolate tilt values based on progress (but don't apply transform yet)
        # We'll apply transform with flutter in update_animation to ensure flutter is applied to flat image
        current_tilt_x = initial_tilt_x + (target_tilt_x - initial_tilt_x) * progress
        current_tilt_z = initial_tilt_z + (target_tilt_z - initial_tilt_z) * progress

        # Don't apply transform here - start with flat image and apply transforms dynamically
        # This ensures flutter and tilt are applied together to the flat image
        frame_widget = FrameWidget(self.frames_container)
        frame_widget.setFixedSize(widget_size)
        # Start with flat pixmap - transforms will be applied in update_animation with flutter
        frame_widget.set_tilted_pixmap(complete_pixmap)

        image_label = QLabel(frame_widget)
        image_label.hide()

        # Position widget at current location
        frame_widget.move(int(current_pos.x()), int(current_pos.y()))

        opacity_effect = QGraphicsOpacityEffect(frame_widget)
        frame_widget.setGraphicsEffect(opacity_effect)
        
        # Check if frame is on screen to set appropriate opacity
        is_on_screen = (current_pos.x() > -widget_size.width() and
                       current_pos.x() < container_size.width() and
                       current_pos.y() > -widget_size.height() and
                       current_pos.y() < container_size.height())
        
        if is_on_screen:
            opacity_effect.setOpacity(1.0)  # Fully visible if on screen
        else:
            opacity_effect.setOpacity(0.0)  # Invisible if off screen

        # Flutter parameters already calculated above, use them here
        frame_data = FrameData(
            widget=frame_widget,
            image_label=image_label,
            start_pos=start_pos,
            end_pos=end_pos,
            control_points=control_points,
            total_distance=total_distance,
            current_distance=current_distance,  # Set to pre-travel distance
            speed=speed,
            size=widget_size,
            tilt_angle=tilt_y,
            opacity_effect=opacity_effect,
            spawn_time=time.time(),  # Track actual spawn time for flutter calculations
            duration=duration,
            tilt_x=current_tilt_x,  # Set to current interpolated value
            tilt_z=current_tilt_z,  # Set to current interpolated value
            initial_tilt_x=initial_tilt_x,
            initial_tilt_z=initial_tilt_z,
            target_tilt_x=target_tilt_x,
            target_tilt_z=target_tilt_z,
            original_pixmap=complete_pixmap,
            flutter_phase_x=flutter_phase_x,
            flutter_phase_z=flutter_phase_z,
            flutter_frequency_x=flutter_freq_x,
            flutter_frequency_z=flutter_freq_z,
            flutter_amplitude_x=flutter_amp_x,
            flutter_amplitude_z=flutter_amp_z,
        )
        frame_data._fading_in = False
        frame_data._entered_screen = is_on_screen  # Mark as entered if already on screen

        # Apply initial transform with flutter to flat image immediately
        # This ensures flutter and tilt are applied together from the start
        elapsed_time = 0.0  # Just spawned, so elapsed time is 0
        flutter_x = (math.sin(2 * math.pi * frame_data.flutter_frequency_x * elapsed_time + frame_data.flutter_phase_x) * frame_data.flutter_amplitude_x +
                    math.sin(4 * math.pi * frame_data.flutter_frequency_x * elapsed_time + frame_data.flutter_phase_x * 1.3) * frame_data.flutter_amplitude_x * 0.15)  # Reduced harmonic for subtlety
        flutter_z = (math.sin(2 * math.pi * frame_data.flutter_frequency_z * elapsed_time + frame_data.flutter_phase_z) * frame_data.flutter_amplitude_z +
                    math.sin(4 * math.pi * frame_data.flutter_frequency_z * elapsed_time + frame_data.flutter_phase_z * 1.5) * frame_data.flutter_amplitude_z * 0.12)  # Reduced harmonic for subtlety
        current_tilt_with_flutter_x = current_tilt_x + flutter_x
        current_tilt_with_flutter_z = current_tilt_z + flutter_z
        initial_tilted_pixmap = self._apply_tilt_transform(
            complete_pixmap,
            current_tilt_with_flutter_x,
            tilt_y,
            current_tilt_with_flutter_z
        )
        frame_widget.set_tilted_pixmap(initial_tilted_pixmap)

        self.active_frames.append(frame_data)
        frame_widget.show()
        frame_widget.raise_()
        frame_widget.update()
        frame_widget.repaint()
        frame_widget.setAttribute(Qt.WA_NoSystemBackground, False)
        frame_widget.setAutoFillBackground(True)

    def _get_position_along_spline_from_points(self, start_pos: QPointF, end_pos: QPointF, 
                                                control_points: List[QPointF], total_distance: float, 
                                                distance: float) -> QPointF:
        """Get position along spline at given distance (helper for pre-travel frames)"""
        if distance <= 0:
            return start_pos
        if distance >= total_distance:
            return end_pos
        t = distance / total_distance
        return self._catmull_rom_eval(control_points, t)

    def _spawn_initial_frames(self):
        """Spawn initial frames already on screen to populate the display"""
        if self.window.current_view_mode != 'slideshow3':
            return
        if not self.frames_container or not self.frames_container.isVisible():
            return
        
        # Spawn 3-6 frames already partway through their journey
        effective_max = self.get_effective_max_frames()
        num_initial_frames = random.randint(3, min(6, effective_max))
        
        for _ in range(num_initial_frames):
            if len(self.active_frames) >= effective_max:
                break
            # Spawn frames at various stages: some just entering, some mid-journey, some almost exiting
            progress_min = random.choice([0.0, 0.1, 0.2, 0.3, 0.5, 0.7])
            progress_max = min(0.95, progress_min + 0.3)
            self._spawn_frame_with_pretravel(progress_min=progress_min, progress_max=progress_max)

    def _generate_spline_path(self, container_size: QSize, frame_size: QSize) -> Tuple[QPointF, QPointF, List[QPointF], float]:
        """Generate a spline path from one edge to the opposite edge"""
        edges = ['left', 'right', 'top', 'bottom']
        entry_edge = random.choice(edges)
        opposite_map = {
            'left': 'right',
            'right': 'left',
            'top': 'bottom',
            'bottom': 'top'
        }
        exit_edge = opposite_map[entry_edge]
        margin = 50
        max_y = max(0, container_size.height() - frame_size.height())
        max_x = max(0, container_size.width() - frame_size.width())
        if entry_edge == 'left':
            start_x = -frame_size.width() - margin
            start_y = random.randint(0, max_y)
        elif entry_edge == 'right':
            start_x = container_size.width() + margin
            start_y = random.randint(0, max_y)
        elif entry_edge == 'top':
            start_x = random.randint(0, max_x)
            start_y = -frame_size.height() - margin
        else:  # bottom
            start_x = random.randint(0, max_x)
            start_y = container_size.height() + margin
        if exit_edge == 'left':
            end_x = -frame_size.width() - margin
            end_y = random.randint(0, max_y)
        elif exit_edge == 'right':
            end_x = container_size.width() + margin
            end_y = random.randint(0, max_y)
        elif exit_edge == 'top':
            end_x = random.randint(0, max_x)
            end_y = -frame_size.height() - margin
        else:  # bottom
            end_x = random.randint(0, max_x)
            end_y = container_size.height() + margin
        start_pos = QPointF(start_x, start_y)
        end_pos = QPointF(end_x, end_y)
        num_control_points = random.randint(SPLINE_CONTROL_POINTS_MIN, SPLINE_CONTROL_POINTS_MAX)
        control_points = [start_pos]
        for i in range(num_control_points):
            margin = 100
            x = random.uniform(margin, container_size.width() - margin)
            y = random.uniform(margin, container_size.height() - margin)
            control_points.append(QPointF(x, y))
        control_points.append(end_pos)
        total_distance = self._calculate_spline_length(control_points)
        return start_pos, end_pos, control_points, total_distance

    def _calculate_spline_length(self, points: List[QPointF]) -> float:
        """Calculate approximate length of spline path"""
        if len(points) < 2:
            return 0.0
        total_length = 0.0
        num_samples = 100
        for i in range(num_samples):
            t1 = i / num_samples
            t2 = (i + 1) / num_samples
            p1 = self._catmull_rom_eval(points, t1)
            p2 = self._catmull_rom_eval(points, t2)
            dx = p2.x() - p1.x()
            dy = p2.y() - p1.y()
            total_length += math.sqrt(dx * dx + dy * dy)
        return total_length

    def _catmull_rom_eval(self, points: List[QPointF], t: float) -> QPointF:
        """Evaluate linear interpolation between points for more linear paths"""
        if len(points) < 2:
            return points[0] if points else QPointF(0, 0)
        n = len(points) - 1
        if n == 0:
            return points[0]
        seg = t * n
        idx = min(int(seg), n - 1)
        local_t = seg - idx
        p1 = points[idx]
        p2 = points[min(idx + 1, len(points) - 1)]
        x = p1.x() + (p2.x() - p1.x()) * local_t
        y = p1.y() + (p2.y() - p1.y()) * local_t
        return QPointF(x, y)

    def _get_position_along_spline(self, frame_data: FrameData, distance: float) -> QPointF:
        """Get position along spline at given distance"""
        if distance <= 0:
            return frame_data.start_pos
        if distance >= frame_data.total_distance:
            return frame_data.end_pos
        t = distance / frame_data.total_distance
        return self._catmull_rom_eval(frame_data.control_points, t)

    def _calculate_max_tilted_size(self, pixmap: QPixmap, tilt_y: float, 
                                    initial_tilt_x: float, initial_tilt_z: float,
                                    target_tilt_x: float, target_tilt_z: float,
                                    flutter_amp_x: float = 3.0, flutter_amp_z: float = 3.0) -> QSize:
        """Calculate maximum size needed to accommodate pixmap at any tilt including flutter oscillations"""
        # Account for flutter oscillations by adding flutter amplitudes to tilt ranges
        # Flutter can add up to flutter_amp_x degrees (plus harmonics) to tilt_x
        # and flutter_amp_z degrees (plus harmonics) to tilt_z
        max_flutter_x = flutter_amp_x * 1.15  # Account for reduced harmonics (1.0 + 0.15)
        max_flutter_z = flutter_amp_z * 1.12  # Account for reduced harmonics (1.0 + 0.12)
        
        # Calculate extreme tilt values including flutter
        min_tilt_x = min(initial_tilt_x, target_tilt_x) - max_flutter_x
        max_tilt_x = max(initial_tilt_x, target_tilt_x) + max_flutter_x
        min_tilt_z = min(initial_tilt_z, target_tilt_z) - max_flutter_z
        max_tilt_z = max(initial_tilt_z, target_tilt_z) + max_flutter_z
        
        # Clamp to reasonable ranges to avoid extreme calculations
        min_tilt_x = max(TILT_X_MIN - 20, min_tilt_x)
        max_tilt_x = min(TILT_X_MAX + 20, max_tilt_x)
        min_tilt_z = max(TILT_Z_MIN - 20, min_tilt_z)
        max_tilt_z = min(TILT_Z_MAX + 20, max_tilt_z)
        
        # Calculate sizes for extreme combinations including flutter
        initial_tilted = self._apply_tilt_transform(pixmap, initial_tilt_x, tilt_y, initial_tilt_z)
        target_tilted = self._apply_tilt_transform(pixmap, target_tilt_x, tilt_y, target_tilt_z)
        max_x_max_z = self._apply_tilt_transform(pixmap, max_tilt_x, tilt_y, max_tilt_z)
        min_x_min_z = self._apply_tilt_transform(pixmap, min_tilt_x, tilt_y, min_tilt_z)
        max_x_min_z = self._apply_tilt_transform(pixmap, max_tilt_x, tilt_y, min_tilt_z)
        min_x_max_z = self._apply_tilt_transform(pixmap, min_tilt_x, tilt_y, max_tilt_z)
        
        # Find maximum width and height across all possibilities including flutter extremes
        max_width = max(
            initial_tilted.width(),
            target_tilted.width(),
            max_x_max_z.width(),
            min_x_min_z.width(),
            max_x_min_z.width(),
            min_x_max_z.width()
        )
        max_height = max(
            initial_tilted.height(),
            target_tilted.height(),
            max_x_max_z.height(),
            min_x_min_z.height(),
            max_x_min_z.height(),
            min_x_max_z.height()
        )
        
        # Clean up temporary pixmaps immediately after use
        initial_tilted = None
        target_tilted = None
        max_x_max_z = None
        min_x_min_z = None
        max_x_min_z = None
        min_x_max_z = None
        
        return QSize(max_width, max_height)

    def _apply_tilt_transform(self, pixmap: QPixmap, tilt_x: float, tilt_y: float, tilt_z: float) -> QPixmap:
        """Apply 3D tilt transform to a pixmap with pronounced perspective distortions"""
        # Simulate 3D: use a QTransform that warps the pixmap by shearing and scaling in X/Y
        # since QTransform does not support full 3D, fake it: use tilt_x for vertical perspective (Y axis),
        # tilt_y for in-plane rotation, tilt_z for a small Z axis rotation (roll).

        # 1. Shear for X, scale for Y (for 3D "look")
        # 2. Rotate around Y (regular rotation)
        # 3. Rotate around Z (roll, subtle)

        # Center transformation about the pixmap center
        center = pixmap.rect().center()

        transform = QTransform()
        # Move center to origin
        transform.translate(center.x(), center.y())

        # Step 1: Dramatic shear for "3D X tilt" (makes top/bottom closer/farther)
        # Increased factor to 0.85 for very pronounced perspective distortion during flutter
        x_shear = math.tan(math.radians(tilt_x)) * 0.85
        y_shear = math.tan(math.radians(tilt_z)) * 0.75  # Increased for dramatic side skew

        if abs(x_shear) > 0.01:
            transform.shear(0, x_shear)
        if abs(y_shear) > 0.01:
            transform.shear(y_shear, 0)

        # Step 2: "Y axis tilt" classic rotation of the plane (the old TILT_ANGLE)
        if abs(tilt_y) > 0.01:
            transform.rotate(tilt_y)

        # Step 3: Dramatic perspective scaling (vertical compression for depth effect)
        # Much more pronounced compression to simulate dramatic fluttering motion
        scale_y = 1.0 - abs(tilt_x) / 35.0  # Changed from 50.0 to 35.0 for much stronger effect
        if scale_y < 0.65:  # Allow more dramatic compression
            scale_y = 0.65
        
        # Add horizontal perspective scaling based on tilt_z for additional depth
        scale_x = 1.0 - abs(tilt_z) / 45.0  # Changed from 60.0 to 45.0 for stronger effect
        if scale_x < 0.75:  # Allow more dramatic horizontal compression
            scale_x = 0.75
        
        transform.scale(scale_x, scale_y)

        # Step 4: Additional dramatic perspective warping - apply non-uniform scaling
        # This creates a trapezoidal distortion effect (keystone effect) for flutter
        # Simulate perspective by scaling top/bottom differently based on tilt_x
        if abs(tilt_x) > 1.5:  # Apply even for smaller tilts for continuous flutter effect
            # Create perspective-like warping: top scales differently than bottom
            perspective_factor = abs(tilt_x) / 40.0  # Normalize to reasonable range
            # Apply additional vertical scaling that varies with tilt (more dramatic)
            perspective_scale_y = 1.0 - perspective_factor * 0.25  # Increased from 0.15 to 0.25
            if perspective_scale_y < 0.80:  # Allow more warping
                perspective_scale_y = 0.80
            transform.scale(1.0, perspective_scale_y)
        
        # Add horizontal perspective warping based on tilt_z
        if abs(tilt_z) > 1.5:
            perspective_factor_z = abs(tilt_z) / 40.0
            perspective_scale_x = 1.0 - perspective_factor_z * 0.20
            if perspective_scale_x < 0.82:
                perspective_scale_x = 0.82
            transform.scale(perspective_scale_x, 1.0)

        # Step 5: More pronounced Z "roll" for fluttering effect
        if abs(tilt_z) > 0.01:
            transform.rotate(tilt_z)

        # Move back
        transform.translate(-center.x(), -center.y())

        return pixmap.transformed(transform, Qt.SmoothTransformation)

    def update_animation(self):
        """Update animation for all active frames"""
        if self.window.current_view_mode != 'slideshow3':
            return
        if not self.frames_container:
            return
        
        # Re-apply cursor hiding if it should be hidden (widget operations reset it)
        if self.cursor_is_hidden:
            current_time = time.time()
            time_since_activity = (current_time - self.last_mouse_activity_time) * 1000
            if time_since_activity >= self.mouse_activity_timeout_ms:
                self.main_window.setCursor(Qt.BlankCursor)
                app = QApplication.instance()
                if app:
                    app.setOverrideCursor(Qt.BlankCursor)
        
        dt = ANIMATION_INTERVAL_MS / 1000.0  # Convert to seconds
        frames_to_remove = []
        for frame_data in self.active_frames:
            frame_data.current_distance += frame_data.speed * dt
            if frame_data.current_distance >= frame_data.total_distance:
                fade_out = QPropertyAnimation(frame_data.opacity_effect, b"opacity")
                fade_out.setDuration(300)
                fade_out.setStartValue(frame_data.opacity_effect.opacity())
                fade_out.setEndValue(0.0)
                fade_out.setEasingCurve(QEasingCurve.InOutQuad)

                def remove_frame(fd=frame_data):
                    # Clean up pixmaps before deleting widget
                    if hasattr(fd.widget, 'clear_pixmap'):
                        fd.widget.clear_pixmap()
                    if fd.original_pixmap and not fd.original_pixmap.isNull():
                        fd.original_pixmap = None
                    fd.widget.hide()
                    fd.widget.setParent(None)
                    fd.widget.deleteLater()
                    if fd in self.active_frames:
                        self.active_frames.remove(fd)
                fade_out.finished.connect(remove_frame)
                fade_out.start()
                frames_to_remove.append(frame_data)
                continue
            new_pos = self._get_position_along_spline(frame_data, frame_data.current_distance)
            frame_data.widget.move(int(new_pos.x()), int(new_pos.y()))
            
            # Interpolate base tilt values based on progress
            progress = frame_data.current_distance / frame_data.total_distance
            base_tilt_x = frame_data.initial_tilt_x + (frame_data.target_tilt_x - frame_data.initial_tilt_x) * progress
            base_tilt_z = frame_data.initial_tilt_z + (frame_data.target_tilt_z - frame_data.initial_tilt_z) * progress
            
            # Add dramatic cyclical flutter oscillations for fluttering effect
            current_time = time.time()
            elapsed_time = current_time - frame_data.spawn_time
            
            # Create subtle flutter oscillations using sine waves
            # Use reduced harmonics for very subtle fluttering motion
            flutter_x = (math.sin(2 * math.pi * frame_data.flutter_frequency_x * elapsed_time + frame_data.flutter_phase_x) * frame_data.flutter_amplitude_x +
                        math.sin(4 * math.pi * frame_data.flutter_frequency_x * elapsed_time + frame_data.flutter_phase_x * 1.3) * frame_data.flutter_amplitude_x * 0.15)  # Reduced harmonic for subtlety
            flutter_z = (math.sin(2 * math.pi * frame_data.flutter_frequency_z * elapsed_time + frame_data.flutter_phase_z) * frame_data.flutter_amplitude_z +
                        math.sin(4 * math.pi * frame_data.flutter_frequency_z * elapsed_time + frame_data.flutter_phase_z * 1.5) * frame_data.flutter_amplitude_z * 0.12)  # Reduced harmonic for subtlety
            
            # Combine base tilt with flutter oscillations
            frame_data.tilt_x = base_tilt_x + flutter_x
            frame_data.tilt_z = base_tilt_z + flutter_z
            
            # Re-apply transform with updated tilt values
            if frame_data.original_pixmap and not frame_data.original_pixmap.isNull():
                tilted_pixmap = self._apply_tilt_transform(
                    frame_data.original_pixmap,
                    frame_data.tilt_x,
                    frame_data.tilt_angle,
                    frame_data.tilt_z
                )
                frame_data.widget.set_tilted_pixmap(tilted_pixmap)
            
            container_size = self.frames_container.size()
            frame_size = frame_data.size
            is_on_screen = (new_pos.x() > -frame_size.width() and
                            new_pos.x() < container_size.width() and
                            new_pos.y() > -frame_size.height() and
                            new_pos.y() < container_size.height())
            if is_on_screen and not getattr(frame_data, '_entered_screen', False):
                frame_data._entered_screen = True
            if is_on_screen:
                current_opacity = frame_data.opacity_effect.opacity()
                if current_opacity < 0.99:
                    if not getattr(frame_data, '_fading_in', False):
                        frame_data._fading_in = True
                        fade_in = QPropertyAnimation(frame_data.opacity_effect, b"opacity", frame_data.widget)
                        fade_in.setDuration(500)
                        fade_in.setStartValue(current_opacity)
                        fade_in.setEndValue(1.0)
                        fade_in.setEasingCurve(QEasingCurve.InOutQuad)

                        frame_data._fade_in_anim = fade_in

                        def fade_complete():
                            frame_data._fading_in = False
                            if hasattr(frame_data, '_fade_in_anim'):
                                delattr(frame_data, '_fade_in_anim')

                        fade_in.finished.connect(fade_complete)
                        fade_in.start()
            if not frame_data.widget.isVisible():
                frame_data.widget.show()
            frame_data.widget.raise_()
        for frame_data in frames_to_remove:
            if frame_data in self.active_frames:
                self.active_frames.remove(frame_data)

    def stop_slideshow3(self, target_mode='thumbnail'):
        """Stop frames slideshow mode"""
        if self.window.current_view_mode != 'slideshow3':
            return
        self.animation_timer.stop()
        self.spawn_timer.stop()
        # Stop cursor hiding timer
        self.cursor_hide_timer.stop()
        self.cursor_is_hidden = False
        # Remove cursor overlay
        if self.cursor_overlay:
            self.cursor_overlay.hide()
            self.cursor_overlay.setParent(None)
            self.cursor_overlay.deleteLater()
            self.cursor_overlay = None
        for frame_data in self.active_frames[:]:
            if frame_data.widget:
                # Clean up pixmaps before deleting widget
                if hasattr(frame_data.widget, 'clear_pixmap'):
                    frame_data.widget.clear_pixmap()
                if frame_data.original_pixmap and not frame_data.original_pixmap.isNull():
                    frame_data.original_pixmap = None
                frame_data.widget.hide()
                frame_data.widget.setParent(None)
                frame_data.widget.deleteLater()
        self.active_frames.clear()
        if self.frames_container:
            self.frames_container.hide()
            self.frames_container.setParent(None)
            self.frames_container.deleteLater()
            self.frames_container = None
        QTimer.singleShot(0, lambda: self._force_cleanup_frames())
        if getattr(self, 'image_container', None):
            self.image_container.show()
        self._restore_stacked_widget_to_initial_state()
        if hasattr(self, 'current_pixmap'):
            self.current_pixmap = None
        if getattr(self, 'image_label', None):
            self.image_label.clear()
            self.image_label.setPixmap(QPixmap())
            self.image_label.setGraphicsEffect(None)
        if target_mode == 'thumbnail':
            self.window.current_view_mode = 'thumbnail'
            self.stacked_widget.setCurrentIndex(0)
            self.window.manage_sidebar_visibility_for_view_mode('thumbnail')
            if hasattr(self.main_window, 'status_bar'):
                settings = self.config.load_settings()
                status_bar_visible = settings.get('status_bar_visible', True)
                if status_bar_visible:
                    self.main_window.status_bar.show()
                else:
                    self.main_window.status_bar.hide()
            if hasattr(self.window, 'update_status_bar_sections'):
                self.window.update_status_bar_sections()
            if hasattr(self.main_window, 'menu_manager'):
                self.main_window.menu_manager.prime_menu_keys_for_view_change()
            QTimer.singleShot(100, self.main_window.efficient_directory_refresh)
        # Save current max_simultaneous_frames to persist keyboard changes
        self.config.update_setting('slideshow3_max_simultaneous_frames', self.max_simultaneous_frames)
        # Restore cursor after all widget operations complete
        QTimer.singleShot(100, self._force_restore_cursor)
        if self.status_notification:
            self.status_notification.show_message("Frames slideshow stopped")

    def _restore_stacked_widget_to_initial_state(self):
        """Restore stacked widget to its initial state as created in setup_browse_view"""
        try:
            if getattr(self, 'stacked_widget', None) and self.stacked_widget.count() > 1:
                browse_view_widget = self.stacked_widget.widget(1)
                if browse_view_widget:
                    browse_view_widget.setStyleSheet("""
                        QWidget {
                            background-color: rgb(0, 0, 0);
                            color: white;
                        }
                    """)
            if getattr(self, 'image_label', None) and hasattr(self, 'image_layout'):
                layout = self.image_layout
                label_in_layout = False
                for i in range(layout.count()):
                    item = layout.itemAt(i)
                    if item and item.widget() == self.image_label:
                        label_in_layout = True
                        break
                if not label_in_layout:
                    next_label_index = -1
                    for i in range(layout.count()):
                        item = layout.itemAt(i)
                        if item and item.widget() == self.slideshow_next_label:
                            next_label_index = i
                            break
                    if next_label_index >= 0:
                        layout.insertWidget(next_label_index, self.image_label)
                    else:
                        for i in range(layout.count()):
                            item = layout.itemAt(i)
                            if item and item.spacerItem() is not None:
                                layout.insertWidget(i + 1, self.image_label)
                                break
                        else:
                            layout.addWidget(self.image_label)
                from PySide6.QtCore import Qt
                self.image_label.setAlignment(Qt.AlignCenter)
                self.image_label.setMinimumSize(100, 100)
                self.image_label.setMaximumSize(16777215, 16777215)
                self.image_label.setScaledContents(False)
                self.image_label.setFocusPolicy(Qt.NoFocus)
                self.image_label.setAttribute(Qt.WA_TransparentForMouseEvents, False)
                self.image_label.setStyleSheet("background-color: transparent;")
                self.image_label.setGraphicsEffect(None)
                self.image_label.clear()
                self.image_label.setPixmap(QPixmap())
                self.image_label.show()
                layout.update()
            if getattr(self, 'slideshow_next_label', None):
                self.slideshow_next_label.hide()
                from PySide6.QtCore import Qt
                self.slideshow_next_label.setAlignment(Qt.AlignCenter)
                self.slideshow_next_label.setMinimumSize(100, 100)
                self.slideshow_next_label.setScaledContents(False)
                self.slideshow_next_label.setFocusPolicy(Qt.NoFocus)
                self.slideshow_next_label.setStyleSheet("background-color: transparent;")
                self.slideshow_next_label.clear()
                self.slideshow_next_label.setGraphicsEffect(None)
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
                self.slideshow_next_label.setMaximumSize(16777215, 16777215)
        except Exception as e:
            pass

    def _create_framed_image_pixmap(self, frame_size: QSize, image_pixmap: QPixmap, image_size: QSize) -> QPixmap:
        """Create a pixmap containing the frame border and image"""
        complete_pixmap = QPixmap(frame_size)
        complete_pixmap.fill(Qt.transparent)
        painter = QPainter(complete_pixmap)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = complete_pixmap.rect()
        border_width = FRAME_BORDER_WIDTH
        gradient_top = QLinearGradient(0, 0, 0, border_width)
        gradient_top.setColorAt(0, FRAME_BORDER_LIGHT)
        gradient_top.setColorAt(1, FRAME_BORDER_COLOR)
        gradient_left = QLinearGradient(0, 0, border_width, 0)
        gradient_left.setColorAt(0, FRAME_BORDER_LIGHT)
        gradient_left.setColorAt(1, FRAME_BORDER_COLOR)
        painter.fillRect(0, 0, rect.width(), border_width, QBrush(gradient_top))
        painter.fillRect(0, 0, border_width, rect.height(), QBrush(gradient_left))
        gradient_bottom = QLinearGradient(0, rect.height() - border_width, 0, rect.height())
        gradient_bottom.setColorAt(0, FRAME_BORDER_COLOR)
        gradient_bottom.setColorAt(1, FRAME_BORDER_DARK)
        gradient_right = QLinearGradient(rect.width() - border_width, 0, rect.width(), 0)
        gradient_right.setColorAt(0, FRAME_BORDER_COLOR)
        gradient_right.setColorAt(1, FRAME_BORDER_DARK)
        painter.fillRect(0, rect.height() - border_width, rect.width(), border_width, QBrush(gradient_bottom))
        painter.fillRect(rect.width() - border_width, 0, border_width, rect.height(), QBrush(gradient_right))
        painter.setPen(QPen(FRAME_BORDER_DARK, 1))
        import random as rnd
        seed = id(complete_pixmap) % 1000
        rnd.seed(seed)
        for i in range(0, rect.width(), 3):
            if rnd.random() < 0.3:
                painter.drawLine(i, border_width // 2, i, border_width - border_width // 2)
                painter.drawLine(i, rect.height() - border_width + border_width // 2,
                                 i, rect.height() - border_width // 2)
        rnd.seed(seed + 1)
        for i in range(0, rect.height(), 3):
            if rnd.random() < 0.3:
                painter.drawLine(border_width // 2, i, border_width - border_width // 2, i)
                painter.drawLine(rect.width() - border_width + border_width // 2, i,
                                 rect.width() - border_width // 2, i)
        # Fill the entire image_size area with the pixmap, ensuring it touches all frame edges
        # This eliminates gaps between the image and frame border
        image_rect = QRect(border_width, border_width, image_size.width(), image_size.height())
        # If pixmap is larger than image_size (due to KeepAspectRatioByExpanding), crop from center
        if image_pixmap.width() > image_size.width() or image_pixmap.height() > image_size.height():
            # Calculate source rectangle to crop from center of pixmap
            source_x = (image_pixmap.width() - image_size.width()) // 2
            source_y = (image_pixmap.height() - image_size.height()) // 2
            source_rect = QRect(source_x, source_y, image_size.width(), image_size.height())
            painter.drawPixmap(image_rect, image_pixmap, source_rect)
        else:
            # Pixmap fits exactly or is smaller, draw it filling the rectangle
            painter.drawPixmap(image_rect, image_pixmap)
        painter.end()
        return complete_pixmap

    def _enforce_max_frames(self):
        """Enforce max_simultaneous_frames limit by removing excess frames"""
        effective_max = self.get_effective_max_frames()
        if len(self.active_frames) <= effective_max:
            return
        excess_count = len(self.active_frames) - effective_max
        frames_to_remove = self.active_frames[:excess_count]
        for frame_data in frames_to_remove:
            if frame_data.widget:
                fade_out = QPropertyAnimation(frame_data.opacity_effect, b"opacity")
                fade_out.setDuration(200)
                fade_out.setStartValue(frame_data.opacity_effect.opacity())
                fade_out.setEndValue(0.0)
                fade_out.setEasingCurve(QEasingCurve.InOutQuad)

                def remove_widget(frame_data=frame_data):
                    if frame_data.widget:
                        # Clean up pixmaps before deleting widget
                        if hasattr(frame_data.widget, 'clear_pixmap'):
                            frame_data.widget.clear_pixmap()
                        if frame_data.original_pixmap and not frame_data.original_pixmap.isNull():
                            frame_data.original_pixmap = None
                        frame_data.widget.hide()
                        frame_data.widget.setParent(None)
                        frame_data.widget.deleteLater()
                    if frame_data in self.active_frames:
                        self.active_frames.remove(frame_data)

                fade_out.finished.connect(remove_widget)
                fade_out.start()

    def _force_cleanup_frames(self):
        """Force cleanup of any remaining frame widgets"""
        for frame_data in self.active_frames[:]:
            if frame_data.widget:
                # Clean up pixmaps before deleting widget
                if hasattr(frame_data.widget, 'clear_pixmap'):
                    frame_data.widget.clear_pixmap()
                if frame_data.original_pixmap and not frame_data.original_pixmap.isNull():
                    frame_data.original_pixmap = None
                frame_data.widget.hide()
                frame_data.widget.setParent(None)
                frame_data.widget.deleteLater()
        self.active_frames.clear()
        if self.frames_container:
            self.frames_container.hide()
            self.frames_container.setParent(None)
            self.frames_container.deleteLater()
            self.frames_container = None
