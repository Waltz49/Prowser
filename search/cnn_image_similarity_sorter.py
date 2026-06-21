"""
cnn_image_similarity_sorter.py

Proof-of-concept: Use a simple CNN (pretrained) from torchvision to reorder
images in displayed_images based on similarity to a given file name.
No caching, minimal error handling, and no GUI dependencies.

Requires: torch, torchvision, PIL
Optional: transformers (for CLIP support)

Author: proof-of-concept for image browser integration
"""

import os
import glob
from PIL import Image
from files.photos_library_paths import is_inside_photos_library_resources_or_scopes

# Lazy import Qt modules for UI components
_QtWidgets = None
_QtCore = None

def _import_qt_modules():
    """Lazy import Qt modules for UI components"""
    global _QtWidgets, _QtCore
    if _QtWidgets is None:
        try:
            from PySide6.QtWidgets import (
                QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, 
                QPushButton, QDoubleSpinBox, QCheckBox, QDialogButtonBox,
                QProgressBar, QApplication, QFileDialog, QWidget, QMessageBox,
                QComboBox
            )
            from PySide6.QtCore import Qt
            _QtWidgets = {
                'QDialog': QDialog,
                'QVBoxLayout': QVBoxLayout,
                'QHBoxLayout': QHBoxLayout,
                'QLabel': QLabel,
                'QLineEdit': QLineEdit,
                'QPushButton': QPushButton,
                'QDoubleSpinBox': QDoubleSpinBox,
                'QCheckBox': QCheckBox,
                'QDialogButtonBox': QDialogButtonBox,
                'QProgressBar': QProgressBar,
                'QApplication': QApplication,
                'QFileDialog': QFileDialog,
                'QWidget': QWidget,
                'QMessageBox': QMessageBox,
                'QComboBox': QComboBox,
            }
            _QtCore = {'Qt': Qt}
        except ImportError:
            _QtWidgets = None
            _QtCore = None
    return _QtWidgets, _QtCore

# Suppress tokenizers parallelism warning (set before importing transformers)
os.environ.setdefault('TOKENIZERS_PARALLELISM', 'false')

# Lazy imports - torch and related modules are imported only when needed
_torch = None
_torch_nn_functional = None
_torchvision_transforms = None
_torchvision_models = None
_ResNet18_Weights = None
_ResNet50_Weights = None
_ResNet101_Weights = None
_CLIP_AVAILABLE = None
_CLIPProcessor = None
_CLIPModel = None

def _ensure_heif_opener():
    """Register pillow_heif via pil_image_io (single idempotent entry)."""
    from pil_image_io import register_heif_opener

    register_heif_opener()


def _import_torch_modules():
    """Lazy import torch and torchvision modules"""
    global _torch, _torch_nn_functional, _torchvision_transforms, _torchvision_models, _ResNet18_Weights, _ResNet50_Weights, _ResNet101_Weights
    if _torch is None:
        os.environ['PYTHONHTTPSVERIFY'] = '0' # allow insecure HTTPS requests for PyTorch models because of SSL certificate issues with fresh macos installs
        import torch
        import torch.nn.functional as F
        from torchvision import transforms, models
        from torchvision.models import ResNet18_Weights, ResNet50_Weights, ResNet101_Weights
        _torch = torch
        _torch_nn_functional = F
        _torchvision_transforms = transforms
        _torchvision_models = models
        _ResNet18_Weights = ResNet18_Weights
        _ResNet50_Weights = ResNet50_Weights
        _ResNet101_Weights = ResNet101_Weights
    return _torch, _torch_nn_functional, _torchvision_transforms, _torchvision_models, _ResNet18_Weights, _ResNet50_Weights, _ResNet101_Weights

def _import_clip_modules():
    """Lazy import CLIP modules"""
    global _CLIP_AVAILABLE, _CLIPProcessor, _CLIPModel
    if _CLIP_AVAILABLE is None:
        try:
            from transformers import CLIPProcessor, CLIPModel
            _CLIP_AVAILABLE = True
            _CLIPProcessor = CLIPProcessor
            _CLIPModel = CLIPModel
        except ImportError:
            _CLIP_AVAILABLE = False
            _CLIPProcessor = None
            _CLIPModel = None
    return _CLIP_AVAILABLE, _CLIPProcessor, _CLIPModel


class ProgressDialogWithStatus:
    """Custom progress dialog with a status line below the progress bar"""
    
    def __init__(self, label_text, cancel_button_text, minimum, maximum, parent=None, window_title=""):
        QtWidgets, QtCore = _import_qt_modules()
        if QtWidgets is None:
            raise ImportError("PySide6.QtWidgets is required for UI components")
        
        QDialog = QtWidgets['QDialog']
        QVBoxLayout = QtWidgets['QVBoxLayout']
        QLabel = QtWidgets['QLabel']
        QProgressBar = QtWidgets['QProgressBar']
        QPushButton = QtWidgets['QPushButton']
        Qt = QtCore['Qt']

        # Subclass QDialog to override keyPressEvent for ESC handling
        class ProgressDialog(QDialog):
            def __init__(self, parent, owner):
                super().__init__(parent)
                self._owner = owner

            def keyPressEvent(self, event):
                # If Escape is pressed, call cancel
                if event.key() == QtCore['Qt'].Key_Escape:
                    self._owner.cancel()
                    event.accept()
                else:
                    super().keyPressEvent(event)

            def reject(self):
                # Triggered by "close", ESC, dialog close, etc: always call cancel
                self._owner.cancel()
            
            def resizeEvent(self, event):
                """Update label height when dialog is resized"""
                super().resizeEvent(event)
                if hasattr(self._owner, '_update_main_label_height'):
                    self._owner._update_main_label_height()

        self._dialog = ProgressDialog(parent, self)

        self.minimum = minimum
        self.maximum = maximum
        self._canceled = False
        
        # Set up the dialog
        if window_title:
            self._dialog.setWindowTitle(window_title)
        self._dialog.setWindowModality(Qt.WindowModal)
        self._dialog.setMinimumWidth(300)
        self._dialog.setMaximumWidth(440)
        self._dialog.setMinimumHeight(140)
        
        # Create layout
        layout = QVBoxLayout(self._dialog)
        layout.setSpacing(10)
        layout.setContentsMargins(20, 20, 20, 20)
        
        from utils import format_progress_label, PROGRESS_LABEL_MAX_WIDTH_PX

        # Main label — elided text, fixed width; no wrap (avoids dialog growing with long paths)
        self.main_label = QLabel(format_progress_label(label_text))
        self.main_label.setWordWrap(False)
        self.main_label.setMaximumWidth(PROGRESS_LABEL_MAX_WIDTH_PX - 40)
        font_metrics = self.main_label.fontMetrics()
        line_height = font_metrics.height()
        self.main_label.setFixedHeight(line_height * 2 + 4)
        layout.addWidget(self.main_label)
        
        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setMinimum(minimum)
        self.progress_bar.setMaximum(maximum)
        self.progress_bar.setValue(minimum)
        layout.addWidget(self.progress_bar)
        
        # Status label
        self.status_label = QLabel("Initializing...")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)
        
        # Files remaining label (above buttons)
        self.files_remaining_label = QLabel("")
        self.files_remaining_label.setWordWrap(True)
        layout.addWidget(self.files_remaining_label)
        
        # Cancel button
        self.cancel_button = QPushButton(cancel_button_text)
        self.cancel_button.clicked.connect(self.cancel)
        self.cancel_button.setStyleSheet("max-width: 100px;")
        layout.addWidget(self.cancel_button)
        
        # Auto-close and auto-reset properties
        self.auto_close = False
        self.auto_reset = False
        self.minimum_duration = 0
        
    def _update_main_label_height(self):
        """No-op; main label uses fixed height with elided text."""

    def setStatusText(self, text):
        """Set the status text shown below the progress bar"""
        from utils import format_progress_label
        self.status_label.setText(format_progress_label(text))
    
    def setFilesRemaining(self, remaining_count=None, text=None, time_estimate=None):
        """Set the files remaining text (above buttons).
        
        Args:
            remaining_count: Number of files remaining to process (None to hide)
            text: Custom text to display (if provided, overrides remaining_count)
            time_estimate: Optional time estimate string to append (e.g., "Est: 2:21")
        """
        if text is not None:
            display_text = text
            if time_estimate:
                display_text = f"{text} ({time_estimate})"
            self.files_remaining_label.setText(display_text)
        elif remaining_count is not None:
            if remaining_count > 0:
                base_text = f"{remaining_count} file{'s' if remaining_count != 1 else ''} remaining"
                if time_estimate:
                    display_text = f"{base_text} ({time_estimate})"
                else:
                    display_text = base_text
                self.files_remaining_label.setText(display_text)
            else:
                self.files_remaining_label.setText("comparing")
        else:
            self.files_remaining_label.setText("")
        
    def setLabelText(self, text):
        """Set the main label text"""
        from utils import format_progress_label
        self.main_label.setText(format_progress_label(text))
        
    def setValue(self, value):
        """Set the progress bar value"""
        self.progress_bar.setValue(value)
        QtWidgets, _ = _import_qt_modules()
        QtWidgets['QApplication'].processEvents()  # Allow UI updates
        
    def value(self):
        """Get the current progress bar value"""
        return self.progress_bar.value()
    
    def maximum(self):
        """Get the maximum progress bar value"""
        return self.progress_bar.maximum()
    
    def setMaximum(self, maximum):
        """Set the maximum progress bar value"""
        self.maximum = maximum
        self.progress_bar.setMaximum(maximum)
        
    def setAutoClose(self, auto_close):
        """Set auto-close behavior"""
        self.auto_close = auto_close
        
    def setAutoReset(self, auto_reset):
        """Set auto-reset behavior"""
        self.auto_reset = auto_reset
        
    def setMinimumDuration(self, duration):
        """Set minimum duration (for compatibility)"""
        self.minimum_duration = duration
        
    def wasCanceled(self):
        """Check if the dialog was canceled"""
        return self._canceled
        
    def cancel(self):
        """Cancel the operation"""
        self._canceled = True
        self._dialog.hide()
        
    def reset(self):
        """Reset the dialog"""
        self._canceled = False
        self.progress_bar.setValue(self.minimum)
        self.files_remaining_label.setText("")
        
    def show(self):
        """Show the dialog"""
        self._dialog.show()
        
    def hide(self):
        """Hide the dialog"""
        self._dialog.hide()
        
    def setWindowModality(self, modality):
        """Set window modality"""
        self._dialog.setWindowModality(modality)
        
    def setWindowTitle(self, title):
        """Set window title"""
        self._dialog.setWindowTitle(title)


class StagedProgressTracker:
    """Helper class to manage multi-stage progress tracking"""
    
    def __init__(self, progress_dialog, images_to_process_count):
        """
        Initialize staged progress tracker
        
        Args:
            progress_dialog: ProgressDialogWithStatus instance
            images_to_process_count: Number of images that need feature extraction
        """
        self.progress_dialog = progress_dialog
        self.images_to_process_count = images_to_process_count
        
        # Stage percentages (out of 100)
        self.MODEL_LOAD_PERCENT = 5
        self.COMPARISON_PERCENT = 10
        
        # Calculate stage boundaries
        if images_to_process_count > 0:
            # We have work to do: model loading (5%), extraction (85%), comparison (10%)
            self.extraction_start = self.MODEL_LOAD_PERCENT
            self.extraction_end = 100 - self.COMPARISON_PERCENT
            self.comparison_start = self.extraction_end
        else:
            # All cached: model loading (5%), comparison (95%)
            self.extraction_start = self.MODEL_LOAD_PERCENT
            self.extraction_end = self.MODEL_LOAD_PERCENT
            self.comparison_start = self.MODEL_LOAD_PERCENT
        
        # Set progress bar maximum to 100 for percentage-based tracking
        self.progress_dialog.setMaximum(100)
        self.progress_dialog.setValue(0)
        
        self.current_stage = None
        
        # Timing tracking for feature extraction estimates
        import time
        self._extraction_start_time = None
        self._last_200_start_time = None
        self._last_200_start_count = 0
        self._time = time
    
    def _format_time_estimate(self, seconds):
        """Format time estimate as hh:mm:ss or mm:ss
        
        Args:
            seconds: Time in seconds (float)
        
        Returns:
            Formatted string like "Est 1:23:45" or "Est 23:45"
        """
        if seconds < 0:
            return ""
        
        total_seconds = int(seconds)
        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60
        secs = total_seconds % 60
        
        if hours > 0:
            return f"Est {hours}:{minutes:02d}:{secs:02d}"
        else:
            return f"Est {minutes}:{secs:02d}"
    
    def _get_time_estimate(self, processed_count, total_count):
        """Calculate time estimate based on last 200 images
        
        Args:
            processed_count: Number of images processed so far
            total_count: Total number of images to process
        
        Returns:
            Formatted time estimate string, or empty string if not enough data
        """
        current_time = self._time.time()
        
        # Initialize start time on first call
        if self._extraction_start_time is None:
            self._extraction_start_time = current_time
            self._last_200_start_time = current_time
            self._last_200_start_count = 0
            return ""
        
        # Check if we've processed at least 200 images since last reset
        images_since_last_200 = processed_count - self._last_200_start_count
        
        # Reset tracking window every 200 images
        if images_since_last_200 >= 200:
            elapsed = current_time - self._last_200_start_time
            # Update tracking window
            self._last_200_start_time = current_time
            self._last_200_start_count = processed_count
            images_since_last_200 = 0
        
        # Need at least 4 seconds elapsed OR 200 images processed to show estimate
        total_elapsed = current_time - self._extraction_start_time
        if total_elapsed < 4.0 and processed_count < 200:
            return ""
        
        # Calculate estimate based on last 200 images window
        if images_since_last_200 > 0:
            elapsed_in_window = current_time - self._last_200_start_time
            if elapsed_in_window > 0:
                avg_time_per_image = elapsed_in_window / images_since_last_200
            else:
                # Fallback to overall average if window is too small
                if processed_count > 0:
                    avg_time_per_image = total_elapsed / processed_count
                else:
                    return ""
        else:
            # Use overall average if we don't have window data yet
            if processed_count > 0:
                avg_time_per_image = total_elapsed / processed_count
            else:
                return ""
        
        # Calculate remaining images and time
        remaining = total_count - processed_count
        if remaining <= 0:
            return ""
        
        estimated_seconds = avg_time_per_image * remaining
        return self._format_time_estimate(estimated_seconds)
    
    def update_model_loading(self, status_text="Loading model..."):
        """Update progress for model loading stage"""
        self.current_stage = "loading_model"
        # Model loading completes at MODEL_LOAD_PERCENT
        self.progress_dialog.setValue(self.MODEL_LOAD_PERCENT)
        self.progress_dialog.setStatusText(status_text)
        self.progress_dialog.setFilesRemaining()  # Clear files remaining during model load
        # Reset timing tracking when starting extraction
        self._extraction_start_time = None
        self._last_200_start_time = None
        self._last_200_start_count = 0
    
    def update_feature_extraction(self, processed_count, total_count, status_text=None):
        """Update progress for feature extraction stage

        Args:
            processed_count: Number of images processed so far (1-indexed)
            total_count: Total number of images to process
            status_text: Optional status text to display (if None, uses default)
        """
        self.current_stage = "examining_images"
        
        if total_count > 0:
            # Update UI only when number remaining is a multiple of 10, or at the start
            remaining = total_count - processed_count + 1
            should_update_ui = (remaining == total_count or remaining % 10 == 0)
            if should_update_ui:
                # Only track timing when updating UI (every 10 items)
                # Initialize timing on first UI update
                if self._extraction_start_time is None:
                    self._extraction_start_time = self._time.time()
                    self._last_200_start_time = self._extraction_start_time
                    self._last_200_start_count = 0
                
                extraction_progress = float(processed_count) / float(total_count)
                current_value = int(self.extraction_start + 
                                   extraction_progress * (self.extraction_end - self.extraction_start))
                self.progress_dialog.setValue(current_value)

                # Get time estimate for files remaining line (only calculated when updating UI)
                time_estimate = self._get_time_estimate(processed_count, total_count)
                
                # Set status text (without time estimate)
                if status_text:
                    self.progress_dialog.setStatusText(status_text)
                else:
                    self.progress_dialog.setStatusText("Extracting and caching features...")

                # Set files remaining with time estimate
                if remaining > 0:
                    self.progress_dialog.setFilesRemaining(remaining_count=remaining, time_estimate=time_estimate)
                else:
                    self.progress_dialog.setFilesRemaining(text="comparing")
        else:
            # All cached, skip to comparison
            self.progress_dialog.setValue(self.comparison_start)
            if status_text:
                self.progress_dialog.setStatusText(status_text)
            self.progress_dialog.setFilesRemaining(text="comparing")
    
    def update_comparison(self):
        """Update progress for comparison stage"""
        self.current_stage = "comparing_images"
        # Comparison completes at 100%
        self.progress_dialog.setValue(100)
        self.progress_dialog.setStatusText("Calculating similarities and sorting results...")
        self.progress_dialog.setFilesRemaining(text="comparing")
    
    def complete(self):
        """Mark progress as complete"""
        self.progress_dialog.setValue(100)


class _TimingTracker:
    """Helper class for tracking timing and calculating estimates in callbacks"""
    
    def __init__(self):
        import time
        self._time = time
        self._start_time = None
        self._last_200_start_time = None
        self._last_200_start_count = 0
    
    def _format_time_estimate(self, seconds):
        """Format time estimate as hh:mm:ss or mm:ss"""
        if seconds < 0:
            return ""
        
        total_seconds = int(seconds)
        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60
        secs = total_seconds % 60
        
        if hours > 0:
            return f"Est: {hours}:{minutes:02d}:{secs:02d}"
        else:
            return f"Est: {minutes}:{secs:02d}"
    
    def get_time_estimate(self, processed_count, total_count):
        """Calculate time estimate based on last 200 images"""
        current_time = self._time.time()
        
        # Initialize start time on first call
        if self._start_time is None:
            self._start_time = current_time
            self._last_200_start_time = current_time
            self._last_200_start_count = 0
            return ""
        
        # Check if we've processed at least 200 images since last reset
        images_since_last_200 = processed_count - self._last_200_start_count
        
        # Reset tracking window every 200 images
        if images_since_last_200 >= 200:
            elapsed = current_time - self._last_200_start_time
            # Update tracking window
            self._last_200_start_time = current_time
            self._last_200_start_count = processed_count
            images_since_last_200 = 0
        
        # Need at least 4 seconds elapsed OR 200 images processed to show estimate
        total_elapsed = current_time - self._start_time
        if total_elapsed < 4.0 and processed_count < 200:
            return ""
        
        # Calculate estimate based on last 200 images window
        if images_since_last_200 > 0:
            elapsed_in_window = current_time - self._last_200_start_time
            if elapsed_in_window > 0:
                avg_time_per_image = elapsed_in_window / images_since_last_200
            else:
                # Fallback to overall average if window is too small
                if processed_count > 0:
                    avg_time_per_image = total_elapsed / processed_count
                else:
                    return ""
        else:
            # Use overall average if we don't have window data yet
            if processed_count > 0:
                avg_time_per_image = total_elapsed / processed_count
            else:
                return ""
        
        # Calculate remaining images and time
        remaining = total_count - processed_count
        if remaining <= 0:
            return ""
        
        estimated_seconds = avg_time_per_image * remaining
        return self._format_time_estimate(estimated_seconds)
    
    def reset(self):
        """Reset timing tracking"""
        self._start_time = None
        self._last_200_start_time = None
        self._last_200_start_count = 0


class CNNSimilarityUIHelper:
    """Helper class for CNN similarity UI interactions (dialogs, progress callbacks)"""
    
    def __init__(self, parent_widget=None, config=None):
        """
        Initialize UI helper.
        
        Args:
            parent_widget: Parent widget for dialogs (typically ImageBrowserWindow)
            config: Config object for accessing settings
        """
        self.parent_widget = parent_widget
        self.config = config
        self._first_similarity_search = True
        self._first_clip_search = True
    
    def _get_button_style(self):
        """Get button style string using centralized function from utils"""
        try:
            from utils import get_dialog_button_box_style
            return get_dialog_button_box_style()
        except ImportError:
            # Fallback if utils not available
            t = self._theme_values()
            return f"""
                QDialogButtonBox QPushButton {{
                    background-color: {t["button_bg"]};
                    color: {t["button_fg"]};
                    border: 1px solid {t["button_border"]};
                    border-radius: 5px;
                    padding: 6px 18px;
                    min-width: 100px;
                    font-size: 13px;
                    font-family: 'Arial Narrow', Arial;
                    letter-spacing: 0.5px;
                }}
                QDialogButtonBox QPushButton:focus {{
                    background-color: {t["dialog_bg"]};
                    color: {t["button_focus_fg"]};
                    border: 1px solid {t["focus_border"]};
                    outline: none;
                }}
                QDialogButtonBox QPushButton:hover {{
                    background-color: {t["button_hover_bg"]};
                    color: {t["button_hover_fg"]};
                    border: 1px solid {t["button_hover_border"]};
                }}
                QDialogButtonBox QPushButton:pressed {{
                    background-color: {t["button_hover_bg"]};
                    color: {t["button_focus_fg"]};
                }}
            """

    def _theme_values(self):
        """Read active UI theme colors from thumbnail constants."""
        import thumbnails.thumbnail_constants as tc
        return {
            "dialog_bg": tc.DIALOG_BACKGROUND_HEX,
            "button_bg": tc.BUTTON_BG_DEFAULT_HEX,
            "button_fg": tc.BUTTON_TEXT_DEFAULT_HEX,
            "button_border": tc.BUTTON_BORDER_DEFAULT_HEX,
            "button_hover_bg": tc.BUTTON_BG_HOVER_HEX,
            "button_hover_fg": tc.BUTTON_TEXT_HOVER_HEX,
            "button_hover_border": tc.BUTTON_BORDER_HOVER_HEX,
            "button_focus_fg": tc.BUTTON_FOCUS_TEXT_HEX,
            "focus_border": tc.CURRENT_IMAGE_BORDER_COLOR_HEX,
            "text_disabled": tc.TEXT_DISABLED_HEX,
            "success": tc.VALIDATION_SUCCESS_COLOR_HEX,
            "error": tc.ERROR_COLOR_HEX,
        }

    def _dialog_shell_stylesheet(self, button_box_style: str) -> str:
        t = self._theme_values()
        return f"""
            QDialog {{
                background-color: {t["dialog_bg"]};
            }}
            QCheckBox:disabled {{
                color: {t["text_disabled"]};
            }}
            {button_box_style}
        """

    def _container_stylesheet(self) -> str:
        return f"QWidget {{ background-color: {self._theme_values()['dialog_bg']}; }}"

    def _dir_input_stylesheet(self) -> str:
        t = self._theme_values()
        return f"""
            QLineEdit {{
                background-color: {t["button_bg"]};
                color: {t["button_fg"]};
                border: 1px solid {t["button_border"]};
                border-radius: 4px;
                padding: 5px;
            }}
            QLineEdit:focus {{
                border-color: {t["focus_border"]};
                color: {t["button_focus_fg"]};
            }}
            QLineEdit:disabled {{
                color: {t["text_disabled"]};
                background-color: {t["dialog_bg"]};
            }}
        """

    def _small_browse_button_stylesheet(self) -> str:
        t = self._theme_values()
        return f"""
            QPushButton {{
                border: 1px solid {t["button_border"]};
                color: {t["button_fg"]};
                background-color: {t["button_bg"]};
                border-radius: 4px;
                font-size: 12pt;
                padding: 0px 8px;
                min-width: 0px;
            }}
            QPushButton:focus {{
                border: 2px solid {t["focus_border"]};
                outline: none;
                color: {t["button_focus_fg"]};
            }}
            QPushButton:hover {{
                background-color: {t["button_hover_bg"]};
                color: {t["button_hover_fg"]};
                border-color: {t["button_hover_border"]};
            }}
            QPushButton:disabled {{
                color: {t["text_disabled"]};
                border-color: {t["button_border"]};
                background-color: {t["dialog_bg"]};
            }}
        """

    def _validation_label_style(self, *, valid: bool, enabled: bool) -> str:
        t = self._theme_values()
        color = t["text_disabled"]
        if enabled:
            color = t["success"] if valid else t["error"]
        return f"color: {color}; font-size: 14px; font-weight: bold;"
    
    def _has_subdirectories(self, directory_path):
        """Check if a directory has any subdirectories"""
        if not directory_path or not os.path.isdir(directory_path):
            return False
        try:
            # Check if there are any subdirectories (not files)
            for item in os.listdir(directory_path):
                item_path = os.path.join(directory_path, item)
                if os.path.isdir(item_path):
                    return True
            return False
        except (OSError, PermissionError):
            return False
    
    def _get_displayed_files_directory(self):
        """Get the directory containing displayed files if all files are from the same directory"""
        if not self.parent_widget:
            return None
        
        # Try to get displayed images
        displayed_files = None
        if hasattr(self.parent_widget, 'get_displayed_images'):
            displayed_files = self.parent_widget.get_displayed_images()
        elif hasattr(self.parent_widget, 'displayed_images'):
            displayed_files = self.parent_widget.displayed_images
        
        if not displayed_files or len(displayed_files) == 0:
            return None
        
        # Get directories of all displayed files
        directories = set()
        for file_path in displayed_files:
            if file_path:
                try:
                    abs_path = os.path.abspath(file_path)
                    if os.path.exists(abs_path):
                        file_dir = os.path.dirname(abs_path)
                        directories.add(file_dir)
                except (OSError, ValueError):
                    # Skip invalid paths
                    continue
        
        # If all files are from the same directory, return it
        if len(directories) == 1:
            return directories.pop()
        
        return None
    
    def create_clip_search_dialog(self, title, label, text="", recursive_default=False, threshold_default=0.20, directory=None, hide_threshold=False):
        """Create a custom dialog for CLIP search with text input, recursive checkbox, and threshold control
        
        Args:
            hide_threshold: If True, hide the threshold control (used when locked files exist)
        """
        QtWidgets, QtCore = _import_qt_modules()
        if QtWidgets is None:
            raise ImportError("PySide6.QtWidgets is required for UI components")
        
        QDialog = QtWidgets['QDialog']
        QVBoxLayout = QtWidgets['QVBoxLayout']
        QHBoxLayout = QtWidgets['QHBoxLayout']
        QCheckBox = QtWidgets['QCheckBox']
        QLabel = QtWidgets['QLabel']
        QLineEdit = QtWidgets['QLineEdit']
        QDoubleSpinBox = QtWidgets['QDoubleSpinBox']
        QPushButton = QtWidgets['QPushButton']
        QDialogButtonBox = QtWidgets['QDialogButtonBox']
        QFileDialog = QtWidgets['QFileDialog']
        Qt = QtCore['Qt']
        
        dialog = QDialog(self.parent_widget)
        dialog.setWindowTitle(title)
        dialog.setModal(True)
        # Set dialog background and button styling using centralized function
        button_box_style = self._get_button_style()
        dialog.setStyleSheet(self._dialog_shell_stylesheet(button_box_style))
        
        layout = QVBoxLayout(dialog)
        layout.setSpacing(14)
        
        # Load saved directory settings
        if self.config:
            settings = self.config.load_settings()
            saved_dir_enabled = settings.get('clip_search_dir_enabled', False)
            saved_dir_path = settings.get('clip_search_dir', '')
        else:
            saved_dir_enabled = False
            saved_dir_path = ''
        
        # Dynamic directory label (will be updated when checkbox changes)
        # Initialize with directory name if directory is provided, otherwise use the label text
        initial_label_text = label
        if directory and os.path.isdir(directory):
            initial_label_text = f"Search in {os.path.basename(directory)}:"
        dir_label = QLabel(initial_label_text)
        dir_label.setWordWrap(True)
        # Calculate proper height for wrapped text (allow up to 3 lines)
        font_metrics = dir_label.fontMetrics()
        line_height = font_metrics.height()
        dir_label.setMinimumHeight(line_height * 3)
        layout.addWidget(dir_label)
        
        # Text input
        text_input = QLineEdit()
        text_input.setText(text)
        text_input.selectAll()  # Select all text for easy replacement
        layout.addWidget(text_input)
        
        # Directory selection line (similar to move tab with checkbox)
        QWidget = QtWidgets['QWidget']
        container = QWidget()
        container.setMinimumHeight(28)
        # Set container background to match dialog
        container.setStyleSheet(self._container_stylesheet())
        # Add 10px left margin to move the line to the right
        dir_selection_layout = QHBoxLayout(container)
        dir_selection_layout.setContentsMargins(0, 0, 0, 0)
        dir_selection_layout.setSpacing(10)
        
        # Checkbox to enable directory selection
        dir_checkbox = QCheckBox()
        dir_checkbox.setToolTip("Use custom directory for search")
        dir_checkbox.setFixedWidth(20)
        dir_checkbox.setChecked(saved_dir_enabled)
        dir_selection_layout.addWidget(dir_checkbox)
        
        # Directory input field
        dir_input = QLineEdit()
        dir_input.setPlaceholderText("Enter directory path for search")
        dir_input.setMinimumHeight(28)
        # Set QLineEdit background to match theme
        dir_input.setStyleSheet(self._dir_input_stylesheet())
        # Prioritize saved directory path if enabled, otherwise use directory parameter
        # If saved_dir_enabled is True, use saved path; otherwise use directory parameter if valid
        # Match CNN dialog logic exactly
        if saved_dir_path :
            dir_input.setText(saved_dir_path)
        elif directory and os.path.isdir(directory):
            dir_input.setText(directory)
        else:
            dir_input.setText("")
        dir_selection_layout.addWidget(dir_input)
        
        # Validation label (icon)
        validation_label = QLabel("")
        validation_label.setFixedWidth(20)
        validation_label.setAlignment(Qt.AlignCenter)
        validation_label.setStyleSheet("QLabel { background-color: transparent; }")
        dir_selection_layout.addWidget(validation_label)
        
        # Browse button
        browse_button = QPushButton("...")
        browse_button.setToolTip("Browse for directory")
        browse_button.setFixedWidth(30)
        browse_button.setFixedHeight(28)
        browse_button.setStyleSheet(self._small_browse_button_stylesheet())
        dir_selection_layout.addWidget(browse_button)
        
        def browse_directory():
            """Open directory picker dialog"""
            current_path = dir_input.text().strip()
            # Use current_path if valid, otherwise use the directory parameter, 
            # or try to get it from parent_widget, or fallback to home directory
            if current_path and os.path.isdir(current_path):
                start_directory = current_path
            elif directory and os.path.isdir(directory):
                start_directory = directory
            elif self.parent_widget and hasattr(self.parent_widget, 'get_current_search_directory'):
                start_directory = self.parent_widget.get_current_search_directory() or os.path.expanduser("~")
            else:
                start_directory = os.path.expanduser("~")
            selected_dir = QFileDialog.getExistingDirectory(
                dialog,
                "Select Directory for Search",
                start_directory
            )
            if selected_dir:
                dir_input.setText(selected_dir)
                # Don't automatically check checkbox - allow populating field even when unchecked
                validate_directory()
                update_dir_label()
                check_recursive_enable()
        
        def validate_directory():
            """Validate directory path and update validation icon and button state"""
            path = dir_input.text().strip()
            ok_button = button_box.button(QDialogButtonBox.Ok)
            
            if not path:
                # Empty path - no icon
                validation_label.setText("")
                validation_label.setToolTip("")
                if ok_button:
                    ok_button.setEnabled(True)
                return True
            
            if os.path.isdir(path):
                # Valid directory - green checkmark
                validation_label.setText("✓" if dir_checkbox.isChecked() else "-")
                validation_label.setStyleSheet(self._validation_label_style(valid=True, enabled=dir_checkbox.isChecked()))
                validation_label.setToolTip(f"Valid directory: {path}")
                if ok_button:
                    ok_button.setEnabled(True)
                return True
            else:
                # Invalid path - red X
                validation_label.setText("✗" if dir_checkbox.isChecked() else "-")
                validation_label.setStyleSheet(self._validation_label_style(valid=False, enabled=dir_checkbox.isChecked()))
                if os.path.exists(path):
                    validation_label.setToolTip(f"Path exists but is not a directory: {path}")
                else:
                    validation_label.setToolTip(f"Path does not exist: {path}")
                # Disable OK button only if directory checkbox is checked and directory is invalid
                # If checkbox is unchecked, enable button regardless of directory validity
                if ok_button:
                    if dir_checkbox.isChecked():
                        ok_button.setEnabled(False)
                    else:
                        ok_button.setEnabled(True)
                return False
        
        def _update_label_height(label_widget):
            """Update label height based on wrapped text content"""
            Qt = QtCore['Qt']
            font_metrics = label_widget.fontMetrics()
            line_height = font_metrics.height()
            text = label_widget.text()
            if not text:
                label_widget.setMinimumHeight(line_height)
                return
            
            # Get the actual width available for the label
            # First try to use the label's actual width if it's been laid out
            label_width = label_widget.width()
            if label_width <= 0:
                # Label not laid out yet - use dialog width minus margins
                dialog_width = dialog.width() if dialog.width() > 0 else 500
                # Account for dialog margins and layout spacing (typically 20px margins + some padding)
                available_width = dialog_width - 60
            else:
                # Use the label's actual width
                available_width = label_width
            
            # First check if text fits on one line without wrapping
            text_width_no_wrap = font_metrics.boundingRect(text).width()
            if text_width_no_wrap <= available_width:
                # Text fits on one line
                label_widget.setMinimumHeight(line_height + 4)
                return
            
            # Text needs wrapping - calculate how many lines
            text_rect = font_metrics.boundingRect(0, 0, available_width, 0, 
                                                  Qt.TextWordWrap | Qt.AlignLeft | Qt.AlignTop, text)
            # Calculate number of lines: boundingRect.height() divided by line_height
            num_lines = max(1, int((text_rect.height() + line_height - 1) / line_height))
            
            # Set height to accommodate wrapped text (add small padding)
            label_widget.setMinimumHeight(line_height * num_lines + 4)
        
        def update_dir_label():
            """Update the directory label at the top"""
            if dir_checkbox.isChecked():
                # Check recursive state - access via closure (recursive_checkbox defined later)
                try:
                    is_recursive = recursive_checkbox.isChecked()
                except NameError:
                    # recursive_checkbox not yet defined, try dialog attribute as fallback
                    is_recursive = getattr(dialog, 'recursive_checkbox', None)
                    if is_recursive:
                        is_recursive = is_recursive.isChecked()
                    else:
                        is_recursive = False
                
                path = dir_input.text().strip()
                if path and os.path.isdir(path):
                    if is_recursive:
                        dir_label.setText(f"Search {os.path.basename(path)} and its subdirectories")
                    else:
                        dir_label.setText(f"Search {os.path.basename(path)}")
                elif directory:
                    if is_recursive:
                        dir_label.setText(f"Search {os.path.basename(directory)} and its subdirectories")
                    else:
                        dir_label.setText(f"Search {os.path.basename(directory)}")
                else:
                    dir_label.setText(label)
                # Update label height based on wrapped text
                _update_label_height(dir_label)
            else:
                # Checkbox unchecked - search happens in displayed images
                # Get the directory that will be walked (for recursive searches)
                search_dir = None
                if directory and os.path.isdir(directory):
                    search_dir = directory
                elif self.parent_widget and hasattr(self.parent_widget, 'get_current_search_directory'):
                    search_dir = self.parent_widget.get_current_search_directory()
                
                # Check recursive state - access via closure (recursive_checkbox defined later)
                try:
                    is_recursive = recursive_checkbox.isChecked()
                except NameError:
                    # recursive_checkbox not yet defined, try dialog attribute as fallback
                    is_recursive = getattr(dialog, 'recursive_checkbox', None)
                    if is_recursive:
                        is_recursive = is_recursive.isChecked()
                    else:
                        is_recursive = False
                
                if is_recursive and search_dir:
                    # Recursive: search in displayed files + recursively in directory
                    dir_label.setText(f"Search in displayed files and files in {os.path.basename(search_dir)}")
                else:
                    # Non-recursive: search only in displayed files
                    dir_label.setText("Search in displayed files")
                # Update label height based on wrapped text
                _update_label_height(dir_label)
        
        def update_dir_field_state():
            """Enable/disable directory field based on checkbox and manage recursive checkbox"""
            enabled = dir_checkbox.isChecked()
            dir_input.setEnabled(enabled)
            # Browse button stays enabled so user can select directory even when checkbox is unchecked
            validation_label.setEnabled(enabled)
            if enabled:
                validate_directory()
                # Check if directory has subdirectories
                path = dir_input.text().strip()
                if path and os.path.isdir(path):
                    has_subs = self._has_subdirectories(path)
                    # Only update recursive_checkbox if it exists
                    if hasattr(dialog, 'recursive_checkbox'):
                        if not has_subs:
                            dialog.recursive_checkbox.setEnabled(False)
                            dialog.recursive_checkbox.setChecked(False)
                        else:
                            dialog.recursive_checkbox.setEnabled(True)
            else:
                # Directory checkbox unchecked - check displayed files/current directory/directory parameter
                displayed_dir = self._get_displayed_files_directory()
                if (not displayed_dir) and self.parent_widget and hasattr(self.parent_widget, 'get_current_search_directory'):
                    displayed_dir = self.parent_widget.get_current_search_directory()
                if (not displayed_dir) and directory and os.path.isdir(directory):
                    displayed_dir = directory
                if displayed_dir and os.path.isdir(displayed_dir):
                    has_subs = self._has_subdirectories(displayed_dir)
                    # Only update recursive_checkbox if it exists
                    if hasattr(dialog, 'recursive_checkbox'):
                        if not has_subs:
                            dialog.recursive_checkbox.setEnabled(False)
                            dialog.recursive_checkbox.setChecked(False)
                        else:
                            dialog.recursive_checkbox.setEnabled(True)
                # When checkbox is unchecked, validate to enable OK button even if directory is invalid
                validate_directory()
            update_dir_label()
        
        def update_recursive_state(checked):
            """Update directory label when recursive checkbox changes"""
            update_dir_label()
            # Re-validate to update OK button state
            validate_directory()
        
        def check_recursive_enable():
            """Check and update recursive checkbox enable state based on directory"""
            path = dir_input.text().strip()
            
            # If directory checkbox is checked or a directory path is set, check that directory
            if dir_checkbox.isChecked() or (path and os.path.isdir(path)):
                if path and os.path.isdir(path):
                    has_subs = self._has_subdirectories(path)
                    if not has_subs:
                        recursive_checkbox.setEnabled(False)
                        recursive_checkbox.setChecked(False)
                    else:
                        recursive_checkbox.setEnabled(True)
                else:
                    recursive_checkbox.setEnabled(True)
            else:
                # Directory checkbox unchecked - check displayed files/current directory/directory parameter
                displayed_dir = self._get_displayed_files_directory()
                if (not displayed_dir) and self.parent_widget and hasattr(self.parent_widget, 'get_current_search_directory'):
                    displayed_dir = self.parent_widget.get_current_search_directory()
                if (not displayed_dir) and directory and os.path.isdir(directory):
                    displayed_dir = directory
                if displayed_dir and os.path.isdir(displayed_dir):
                    has_subs = self._has_subdirectories(displayed_dir)
                    if not has_subs:
                        recursive_checkbox.setEnabled(False)
                        recursive_checkbox.setChecked(False)
                    else:
                        recursive_checkbox.setEnabled(True)
                else:
                    recursive_checkbox.setEnabled(True)
        
        browse_button.clicked.connect(browse_directory)
        dir_input.textChanged.connect(lambda: (validate_directory(), update_dir_label(), check_recursive_enable()))
        dir_checkbox.toggled.connect(update_dir_field_state)
        
        layout.addWidget(container)
        
        # Recursive checkbox
        # Get depth from search_depth setting for tooltip
        if self.config:
            max_depth = settings.get('search_depth', 4)
        else:
            max_depth = 4
        recursive_checkbox = QCheckBox(f"Recursive (search up to {max_depth} directories deep)")
        recursive_checkbox.setToolTip(f"If checked, searches recursively in subdirectories (up to {max_depth} levels)\nand opens results in a new level.\nDepth is controlled by 'Search depth' in the Directories settings tab.")
        recursive_checkbox.setChecked(recursive_default)
        layout.addWidget(recursive_checkbox)
        recursive_checkbox.toggled.connect(update_recursive_state)
        
        # Threshold control (hidden when locked files exist)
        threshold_layout = QHBoxLayout()
        threshold_label = QLabel("Similarity Threshold:")
        threshold_label.setContentsMargins(28, 0, 0, 0)
        threshold_spinbox = QDoubleSpinBox()
        threshold_spinbox.setRange(0.0, 1.0)
        threshold_spinbox.setSingleStep(0.01)
        threshold_spinbox.setDecimals(2)
        threshold_spinbox.setValue(threshold_default)
        threshold_spinbox.setToolTip(
            "Minimum similarity score (0.0-1.0) for filtering results.\n"
            "Lower values (0.15-0.25): More inclusive, shows more results.\n"
            "Higher values (0.30-0.40): More strict, shows only highly matching images.\n"
            "Always applies to filter search results."
        )
        threshold_layout.addWidget(threshold_label)
        threshold_layout.addWidget(threshold_spinbox)
        threshold_layout.addStretch()
        
        # Hide threshold control if hide_threshold is True (when locked files exist)
        if hide_threshold:
            threshold_label.setVisible(False)
            threshold_spinbox.setVisible(False)
            threshold_layout.setContentsMargins(0, 0, 0, 0)
            threshold_layout.setSpacing(0)
        
        # Always add to layout (but it will be hidden if hide_threshold is True)
        layout.addLayout(threshold_layout)
        
        # Buttons
        button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        button_box.accepted.connect(dialog.accept)
        button_box.rejected.connect(dialog.reject)
        layout.addWidget(button_box)
        
        # Store references for access after exec
        dialog.text_input = text_input
        dialog.recursive_checkbox = recursive_checkbox
        dialog.threshold_spinbox = threshold_spinbox
        dialog.dir_checkbox = dir_checkbox
        dialog.dir_input = dir_input
        dialog.validation_label = validation_label
        
        # Immediately check recursive state after checkbox is stored
        check_recursive_enable()
        
        # Initial setup - ensure label is updated with directory
        update_dir_field_state()
        update_recursive_state(recursive_default)
        # Explicitly call update_dir_label() to ensure it's set correctly
        update_dir_label()
        
        # Set OK button as default
        ok_button = button_box.button(QDialogButtonBox.Ok)
        if ok_button:
            ok_button.setDefault(True)
        
        # Set focus to text input field when dialog is displayed
        text_input.setFocus()
        
        return dialog
    
    def create_similarity_search_dialog(self, directory=None, recursive_default=False):
        """Create a custom dialog for CNN similarity search with recursive checkbox"""
        QtWidgets, QtCore = _import_qt_modules()
        if QtWidgets is None:
            raise ImportError("PySide6.QtWidgets is required for UI components")
        
        QDialog = QtWidgets['QDialog']
        QVBoxLayout = QtWidgets['QVBoxLayout']
        QHBoxLayout = QtWidgets['QHBoxLayout']
        QCheckBox = QtWidgets['QCheckBox']
        QLabel = QtWidgets['QLabel']
        QLineEdit = QtWidgets['QLineEdit']
        QPushButton = QtWidgets['QPushButton']
        QDialogButtonBox = QtWidgets['QDialogButtonBox']
        QFileDialog = QtWidgets['QFileDialog']
        QWidget = QtWidgets['QWidget']
        Qt = QtCore['Qt']
        
        dialog = QDialog(self.parent_widget)
        dialog.setWindowTitle("Find Similar Images")
        dialog.setModal(True)
        # Set dialog background and button styling using centralized function
        button_box_style = self._get_button_style()
        dialog.setStyleSheet(self._dialog_shell_stylesheet(button_box_style))
        
        layout = QVBoxLayout(dialog)
        layout.setSpacing(14)
        
        # Load saved directory settings
        if self.config:
            settings = self.config.load_settings()
            saved_dir_enabled = settings.get('cnn_search_dir_enabled', False)
            saved_dir_path = settings.get('cnn_search_dir', '')
        else:
            saved_dir_enabled = False
            saved_dir_path = ''
        
        # Dynamic directory label (will be updated when checkbox changes)
        dir_label = QLabel("Find images similar to the selected image(s):")
        dir_label.setWordWrap(True)
        # Calculate proper height for wrapped text (allow up to 3 lines)
        font_metrics = dir_label.fontMetrics()
        line_height = font_metrics.height()
        dir_label.setMinimumHeight(line_height * 3)
        layout.addWidget(dir_label)
        
        # Directory selection line (similar to move tab with checkbox)
        container = QWidget()
        container.setMinimumHeight(28)
        # Set container background to match dialog
        container.setStyleSheet(self._container_stylesheet())
        # Add 10px left margin to move the line to the right
        dir_selection_layout = QHBoxLayout(container)
        dir_selection_layout.setContentsMargins(0, 0, 0, 0)
        dir_selection_layout.setSpacing(10)
        
        # Checkbox to enable directory selection
        dir_checkbox = QCheckBox()
        dir_checkbox.setToolTip("Use custom directory for search")
        dir_checkbox.setFixedWidth(20)
        dir_checkbox.setChecked(saved_dir_enabled)
        dir_selection_layout.addWidget(dir_checkbox)
        
        # Directory input field
        dir_input = QLineEdit()
        dir_input.setPlaceholderText("Enter directory path for search")
        dir_input.setMinimumHeight(28)
        # Set QLineEdit background to match theme
        dir_input.setStyleSheet(self._dir_input_stylesheet())
        # Prioritize saved directory path if enabled, otherwise use directory parameter
        # If saved_dir_enabled is True, use saved path; otherwise use directory parameter if valid
        if  saved_dir_path :
            dir_input.setText(saved_dir_path)
        elif directory and os.path.isdir(directory):
            dir_input.setText(directory)
        else:
            dir_input.setText("")
        dir_selection_layout.addWidget(dir_input)
        
        # Validation label (icon)
        validation_label = QLabel("")
        validation_label.setFixedWidth(20)
        validation_label.setAlignment(Qt.AlignCenter)
        validation_label.setStyleSheet("QLabel { background-color: transparent; }")
        dir_selection_layout.addWidget(validation_label)
        
        # Browse button
        browse_button = QPushButton("...")
        browse_button.setToolTip("Browse for directory")
        browse_button.setFixedWidth(30)
        browse_button.setFixedHeight(28)
        browse_button.setStyleSheet(self._small_browse_button_stylesheet())
        dir_selection_layout.addWidget(browse_button)
        
        def browse_directory():
            """Open directory picker dialog"""
            current_path = dir_input.text().strip()
            # Use current_path if valid, otherwise use the directory parameter, 
            # or try to get it from parent_widget, or fallback to home directory
            if current_path and os.path.isdir(current_path):
                start_directory = current_path
            elif directory and os.path.isdir(directory):
                start_directory = directory
            elif self.parent_widget and hasattr(self.parent_widget, 'get_current_search_directory'):
                start_directory = self.parent_widget.get_current_search_directory() or os.path.expanduser("~")
            else:
                start_directory = os.path.expanduser("~")
            selected_dir = QFileDialog.getExistingDirectory(
                dialog,
                "Select Directory for Search",
                start_directory
            )
            if selected_dir:
                dir_input.setText(selected_dir)
                # Don't automatically check checkbox - allow populating field even when unchecked
                validate_directory()
                update_dir_label()
                check_recursive_enable()
        
        def validate_directory():
            """Validate directory path and update validation icon and button state"""
            path = dir_input.text().strip()
            ok_button = button_box.button(QDialogButtonBox.Ok)
            
            if not path:
                # Empty path - no icon
                validation_label.setText("")
                validation_label.setToolTip("")
                if ok_button:
                    ok_button.setEnabled(True)
                return True
            
            if os.path.isdir(path):
                # Valid directory - green checkmark
                validation_label.setText("✓" if dir_checkbox.isChecked() else "-")
                validation_label.setStyleSheet(self._validation_label_style(valid=True, enabled=dir_checkbox.isChecked()))
                validation_label.setToolTip(f"Valid directory: {path}")
                if ok_button:
                    ok_button.setEnabled(True)
                return True
            else:
                # Invalid path - red X
                validation_label.setText("✗" if dir_checkbox.isChecked() else "-")
                validation_label.setStyleSheet(self._validation_label_style(valid=False, enabled=dir_checkbox.isChecked()))
                if os.path.exists(path):
                    validation_label.setToolTip(f"Path exists but is not a directory: {path}")
                else:
                    validation_label.setToolTip(f"Path does not exist: {path}")
                # Disable OK button only if directory checkbox is checked and directory is invalid
                # If checkbox is unchecked, enable button regardless of directory validity
                if ok_button:
                    if dir_checkbox.isChecked():
                        ok_button.setEnabled(False)
                    else:
                        ok_button.setEnabled(True)
                return False
        
        def _update_label_height(label_widget):
            """Update label height based on wrapped text content"""
            Qt = QtCore['Qt']
            font_metrics = label_widget.fontMetrics()
            line_height = font_metrics.height()
            text = label_widget.text()
            if not text:
                label_widget.setMinimumHeight(line_height)
                return
            
            # Get the actual width available for the label
            # First try to use the label's actual width if it's been laid out
            label_width = label_widget.width()
            if label_width <= 0:
                # Label not laid out yet - use dialog width minus margins
                dialog_width = dialog.width() if dialog.width() > 0 else 500
                # Account for dialog margins and layout spacing (typically 20px margins + some padding)
                available_width = dialog_width - 60
            else:
                # Use the label's actual width
                available_width = label_width
            
            # First check if text fits on one line without wrapping
            text_width_no_wrap = font_metrics.boundingRect(text).width()
            if text_width_no_wrap <= available_width:
                # Text fits on one line
                label_widget.setMinimumHeight(line_height + 4)
                return
            
            # Text needs wrapping - calculate how many lines
            text_rect = font_metrics.boundingRect(0, 0, available_width, 0, 
                                                  Qt.TextWordWrap | Qt.AlignLeft | Qt.AlignTop, text)
            # Calculate number of lines: boundingRect.height() divided by line_height
            num_lines = max(1, int((text_rect.height() + line_height - 1) / line_height))
            
            # Set height to accommodate wrapped text (add small padding)
            label_widget.setMinimumHeight(line_height * num_lines + 4)
        
        def update_dir_label():
            """Update the directory label at the top"""
            if dir_checkbox.isChecked():
                # Check recursive state - access via closure (recursive_checkbox defined later)
                try:
                    is_recursive = recursive_checkbox.isChecked()
                except NameError:
                    # recursive_checkbox not yet defined, try dialog attribute as fallback
                    is_recursive = getattr(dialog, 'recursive_checkbox', None)
                    if is_recursive:
                        is_recursive = is_recursive.isChecked()
                    else:
                        is_recursive = False
                
                path = dir_input.text().strip()
                if path and os.path.isdir(path):
                    if is_recursive:
                        dir_label.setText(f"Search {os.path.basename(path)} and its subdirectories")
                    else:
                        dir_label.setText(f"Search {os.path.basename(path)}")
                elif directory:
                    if is_recursive:
                        dir_label.setText(f"Search {os.path.basename(directory)} and its subdirectories")
                    else:
                        dir_label.setText(f"Search {os.path.basename(directory)}")
                else:
                    dir_label.setText("Find images similar to the selected image(s)")
                # Update label height based on wrapped text
                _update_label_height(dir_label)
            else:
                # Checkbox unchecked - search happens in displayed images
                # Get the directory that will be walked (for recursive searches)
                search_dir = None
                if directory and os.path.isdir(directory):
                    search_dir = directory
                elif self.parent_widget and hasattr(self.parent_widget, 'get_current_search_directory'):
                    search_dir = self.parent_widget.get_current_search_directory()
                
                # Check recursive state - access via closure (recursive_checkbox defined later)
                try:
                    is_recursive = recursive_checkbox.isChecked()
                except NameError:
                    # recursive_checkbox not yet defined, try dialog attribute as fallback
                    is_recursive = getattr(dialog, 'recursive_checkbox', None)
                    if is_recursive:
                        is_recursive = is_recursive.isChecked()
                    else:
                        is_recursive = False
                
                if is_recursive and search_dir:
                    # Recursive: search in displayed files + recursively in directory
                    dir_label.setText(f"Search in displayed files and files in {os.path.basename(search_dir)}")
                else:
                    # Non-recursive: search only in displayed files
                    dir_label.setText("Search in displayed files")
                # Update label height based on wrapped text
                _update_label_height(dir_label)
        
        def update_dir_field_state():
            """Enable/disable directory field based on checkbox and manage recursive checkbox"""
            enabled = dir_checkbox.isChecked()
            dir_input.setEnabled(enabled)
            # Browse button stays enabled so user can select directory even when checkbox is unchecked
            validation_label.setEnabled(enabled)
            if enabled:
                validate_directory()
                # Check if directory has subdirectories
                path = dir_input.text().strip()
                if path and os.path.isdir(path):
                    has_subs = self._has_subdirectories(path)
                    # Only update recursive_checkbox if it exists
                    if hasattr(dialog, 'recursive_checkbox'):
                        if not has_subs:
                            dialog.recursive_checkbox.setEnabled(False)
                            dialog.recursive_checkbox.setChecked(False)
                        else:
                            dialog.recursive_checkbox.setEnabled(True)
            else:
                # Directory checkbox unchecked - check displayed files/current directory/directory parameter
                displayed_dir = self._get_displayed_files_directory()
                if (not displayed_dir) and self.parent_widget and hasattr(self.parent_widget, 'get_current_search_directory'):
                    displayed_dir = self.parent_widget.get_current_search_directory()
                if (not displayed_dir) and directory and os.path.isdir(directory):
                    displayed_dir = directory
                if displayed_dir and os.path.isdir(displayed_dir):
                    has_subs = self._has_subdirectories(displayed_dir)
                    # Only update recursive_checkbox if it exists
                    if hasattr(dialog, 'recursive_checkbox'):
                        if not has_subs:
                            dialog.recursive_checkbox.setEnabled(False)
                            dialog.recursive_checkbox.setChecked(False)
                        else:
                            dialog.recursive_checkbox.setEnabled(True)
            update_dir_label()
            # Re-validate to update OK button state
            validate_directory()
        
        def update_recursive_state(checked):
            """Update directory label when recursive checkbox changes"""
            update_dir_label()
            # Re-validate to update OK button state
            validate_directory()
        
        def check_recursive_enable():
            """Check and update recursive checkbox enable state based on directory"""
            path = dir_input.text().strip()
            
            # If directory checkbox is checked or a directory path is set, check that directory
            if dir_checkbox.isChecked() or (path and os.path.isdir(path)):
                if path and os.path.isdir(path):
                    has_subs = self._has_subdirectories(path)
                    if not has_subs:
                        recursive_checkbox.setEnabled(False)
                        recursive_checkbox.setChecked(False)
                    else:
                        recursive_checkbox.setEnabled(True)
                else:
                    recursive_checkbox.setEnabled(True)
            else:
                # Directory checkbox unchecked - check displayed files/current directory/directory parameter
                displayed_dir = self._get_displayed_files_directory()
                if (not displayed_dir) and self.parent_widget and hasattr(self.parent_widget, 'get_current_search_directory'):
                    displayed_dir = self.parent_widget.get_current_search_directory()
                if (not displayed_dir) and directory and os.path.isdir(directory):
                    displayed_dir = directory
                if displayed_dir and os.path.isdir(displayed_dir):
                    has_subs = self._has_subdirectories(displayed_dir)
                    if not has_subs:
                        recursive_checkbox.setEnabled(False)
                        recursive_checkbox.setChecked(False)
                    else:
                        recursive_checkbox.setEnabled(True)
                else:
                    recursive_checkbox.setEnabled(True)
        
        browse_button.clicked.connect(browse_directory)
        dir_input.textChanged.connect(lambda: (validate_directory(), update_dir_label(), check_recursive_enable()))
        dir_checkbox.toggled.connect(update_dir_field_state)
        
        layout.addWidget(container)
        
        # Recursive checkbox
        # Get depth from search_depth setting for tooltip
        if self.config:
            max_depth = settings.get('search_depth', 4)
        else:
            max_depth = 4
        recursive_checkbox = QCheckBox(f"Recursive (search up to {max_depth} directories deep)")
        recursive_checkbox.setToolTip(f"If checked, searches recursively in subdirectories (up to {max_depth} levels)\nand opens results in a new level.\nDepth is controlled by 'Search depth' in the Directories settings tab.")
        recursive_checkbox.setChecked(recursive_default)
        layout.addWidget(recursive_checkbox)
        recursive_checkbox.toggled.connect(update_recursive_state)
        
        # Buttons
        button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        button_box.accepted.connect(dialog.accept)
        button_box.rejected.connect(dialog.reject)
        layout.addWidget(button_box)
        
        # Store references for access after exec
        dialog.recursive_checkbox = recursive_checkbox
        dialog.dir_checkbox = dir_checkbox
        dialog.dir_input = dir_input
        dialog.validation_label = validation_label
        
        # Immediately check recursive state after checkbox is stored
        check_recursive_enable()
        
        # Initial setup
        update_dir_field_state()
        update_recursive_state(recursive_default)
        
        # Set OK button as default and focused
        ok_button = button_box.button(QDialogButtonBox.Ok)
        if ok_button:
            ok_button.setDefault(True)
            ok_button.setFocus()
        
        return dialog
    
    def create_person_search_dialog(self, names, ids, saved_subject_id="", saved_recursive=False, saved_dir_enabled=False, saved_dir_path="", directory=None, samples_per_subject=None):
        """Create a dialog for Search by person with the same directory/scope controls as cmd-K (create_similarity_search_dialog).
        
        Args:
            names: List of person display names for the combo
            ids: List of subject ids corresponding to names
            saved_subject_id: Last-used subject id to pre-select
            saved_recursive: Default for recursive checkbox
            saved_dir_enabled: Default for directory checkbox
            saved_dir_path: Default directory path when enabled
            directory: Current directory (e.g. from get_current_search_directory) for pre-fill
            samples_per_subject: List aligned with names; each item is 0–4 (path, embedding) tuples for that person's samples
        """
        QtWidgets, QtCore = _import_qt_modules()
        if QtWidgets is None:
            raise ImportError("PySide6.QtWidgets is required for UI components")
        
        QDialog = QtWidgets['QDialog']
        QVBoxLayout = QtWidgets['QVBoxLayout']
        QHBoxLayout = QtWidgets['QHBoxLayout']
        QCheckBox = QtWidgets['QCheckBox']
        QLabel = QtWidgets['QLabel']
        QLineEdit = QtWidgets['QLineEdit']
        QPushButton = QtWidgets['QPushButton']
        QDialogButtonBox = QtWidgets['QDialogButtonBox']
        QFileDialog = QtWidgets['QFileDialog']
        QWidget = QtWidgets['QWidget']
        QComboBox = QtWidgets['QComboBox']
        Qt = QtCore['Qt']
        
        dialog = QDialog(self.parent_widget)
        dialog.setWindowTitle("Search by person")
        dialog.setModal(True)
        button_box_style = self._get_button_style()
        dialog.setStyleSheet(self._dialog_shell_stylesheet(button_box_style))
        
        layout = QVBoxLayout(dialog)
        layout.setSpacing(14)
        
        # Dynamic directory label (same behavior as create_similarity_search_dialog)
        dir_label = QLabel("Search in displayed files")
        dir_label.setWordWrap(True)
        font_metrics = dir_label.fontMetrics()
        line_height = font_metrics.height()
        dir_label.setMinimumHeight(line_height * 3)
        layout.addWidget(dir_label)
        
        # Person selection: label + combo on the left; 1–4 face thumbs on the right (Settings Faces source)
        _TH = 96
        _GAP = 6
        fs = list(samples_per_subject or [])
        while len(fs) < len(ids):
            fs.append([])
        fs = fs[:len(ids)]

        person_header = QWidget()
        person_row = QHBoxLayout(person_header)
        person_row.setContentsMargins(0, 0, 0, 0)
        person_row.setSpacing(12)
        left_col = QVBoxLayout()
        left_col.setSpacing(6)
        left_col.addWidget(QLabel("Choose a person:"))
        combo = QComboBox()
        combo.addItems(names)
        left_col.addWidget(combo)
        person_row.addLayout(left_col, 1)

        thumbs_outer = QWidget()
        thumbs_layout = QHBoxLayout(thumbs_outer)
        thumbs_layout.setContentsMargins(0, 0, 0, 0)
        thumbs_layout.setSpacing(_GAP)
        thumb_labels = []
        for _ in range(4):
            tl = QLabel()
            tl.setFixedSize(_TH, _TH)
            tl.setAlignment(Qt.AlignCenter)
            tl.setStyleSheet(f"background: {self._theme_values()['button_bg']};")
            thumb_labels.append(tl)
            thumbs_layout.addWidget(tl)
        person_row.addWidget(thumbs_outer, 0, Qt.AlignTop)

        def _apply_dialog_min_width(num_thumbs_visible: int):
            """Widen dialog for thumb strip + combo column (num_thumbs_visible 1–4)."""
            n = max(1, min(4, num_thumbs_visible))
            thumb_strip_w = n * _TH + max(0, n - 1) * _GAP
            dialog.setMinimumWidth(max(420, 248 + thumb_strip_w + 28))

        def update_person_thumbs():
            from faces.face_sample_thumbnail import ensure_face_sample_thumbnail
            idx = combo.currentIndex()
            raw = fs[idx] if 0 <= idx < len(fs) else []
            entries = [(p, e) for p, e in raw[:4] if e and isinstance(e, list)]
            n_strip = len(entries) if entries else 1
            _apply_dialog_min_width(n_strip)
            tw = n_strip * _TH + max(0, n_strip - 1) * _GAP if entries else _TH
            thumbs_outer.setFixedWidth(tw)
            for i in range(4):
                tl = thumb_labels[i]
                if i < len(entries):
                    tl.setVisible(True)
                    path, emb = entries[i]
                    try:
                        px = ensure_face_sample_thumbnail(path or "", emb)
                    except Exception:
                        px = None
                    if px is not None and not px.isNull():
                        tl.setPixmap(px)
                        tl.setText("")
                    else:
                        tl.clear()
                        tl.setText("?")
                elif i == 0 and not entries:
                    tl.setVisible(True)
                    tl.clear()
                    tl.setText("?")
                else:
                    tl.setVisible(False)
                    tl.clear()
                    tl.setText("")

        combo.currentIndexChanged.connect(lambda _=None: update_person_thumbs())
        layout.addWidget(person_header)
        
        # Directory selection line (same as cmd-K)
        container = QWidget()
        container.setMinimumHeight(28)
        container.setStyleSheet(self._container_stylesheet())
        dir_selection_layout = QHBoxLayout(container)
        dir_selection_layout.setContentsMargins(0, 0, 0, 0)
        dir_selection_layout.setSpacing(10)
        
        dir_checkbox = QCheckBox()
        dir_checkbox.setToolTip("Use custom directory for search")
        dir_checkbox.setFixedWidth(20)
        dir_checkbox.setChecked(saved_dir_enabled)
        dir_selection_layout.addWidget(dir_checkbox)
        
        dir_input = QLineEdit()
        dir_input.setPlaceholderText("Enter directory path for search")
        dir_input.setMinimumHeight(28)
        dir_input.setStyleSheet(self._dir_input_stylesheet())
        if saved_dir_path:
            dir_input.setText(saved_dir_path)
        elif directory and os.path.isdir(directory):
            dir_input.setText(directory)
        else:
            dir_input.setText("")
        dir_selection_layout.addWidget(dir_input)
        
        validation_label = QLabel("")
        validation_label.setFixedWidth(20)
        validation_label.setAlignment(Qt.AlignCenter)
        validation_label.setStyleSheet("QLabel { background-color: transparent; }")
        dir_selection_layout.addWidget(validation_label)
        
        browse_button = QPushButton("...")
        browse_button.setToolTip("Browse for directory")
        browse_button.setFixedWidth(30)
        browse_button.setFixedHeight(28)
        browse_button.setStyleSheet(self._small_browse_button_stylesheet())
        dir_selection_layout.addWidget(browse_button)
        
        def _resolved_dir_input():
            raw = dir_input.text().strip()
            return os.path.expanduser(raw) if raw else ""
        
        def browse_directory():
            current_path = dir_input.text().strip()
            start_directory = None
            if current_path:
                expanded = os.path.expanduser(current_path)
                if os.path.isdir(expanded):
                    start_directory = expanded
            if start_directory is None and directory and os.path.isdir(directory):
                start_directory = directory
            elif start_directory is None and self.parent_widget and hasattr(self.parent_widget, 'get_current_search_directory'):
                start_directory = self.parent_widget.get_current_search_directory() or os.path.expanduser("~")
            elif start_directory is None:
                start_directory = os.path.expanduser("~")
            selected_dir = QFileDialog.getExistingDirectory(
                dialog, "Select Directory for Search", start_directory
            )
            if selected_dir:
                dir_input.setText(selected_dir)
                validate_directory()
                update_dir_label()
                check_recursive_enable()
        
        def validate_directory():
            path = dir_input.text().strip()
            resolved = _resolved_dir_input()
            ok_button = button_box.button(QDialogButtonBox.Ok)
            if not path:
                validation_label.setText("")
                validation_label.setToolTip("")
                if ok_button:
                    ok_button.setEnabled(True)
                return True
            if resolved and os.path.isdir(resolved):
                validation_label.setText("✓" if dir_checkbox.isChecked() else "-")
                validation_label.setStyleSheet(self._validation_label_style(valid=True, enabled=dir_checkbox.isChecked()))
                validation_label.setToolTip(f"Valid directory: {resolved}")
                if ok_button:
                    ok_button.setEnabled(True)
                return True
            else:
                validation_label.setText("✗" if dir_checkbox.isChecked() else "-")
                validation_label.setStyleSheet(self._validation_label_style(valid=False, enabled=dir_checkbox.isChecked()))
                if resolved and os.path.exists(resolved):
                    validation_label.setToolTip(f"Path exists but is not a directory: {resolved}")
                else:
                    validation_label.setToolTip(f"Path does not exist: {resolved or path}")
                if ok_button:
                    if dir_checkbox.isChecked():
                        ok_button.setEnabled(False)
                    else:
                        ok_button.setEnabled(True)
                return False
        
        def _update_label_height(label_widget):
            font_metrics = label_widget.fontMetrics()
            line_height = font_metrics.height()
            text = label_widget.text()
            if not text:
                label_widget.setMinimumHeight(line_height)
                return
            label_width = label_widget.width()
            if label_width <= 0:
                dialog_width = dialog.width() if dialog.width() > 0 else 500
                available_width = dialog_width - 60
            else:
                available_width = label_width
            text_width_no_wrap = font_metrics.boundingRect(text).width()
            if text_width_no_wrap <= available_width:
                label_widget.setMinimumHeight(line_height + 4)
                return
            text_rect = font_metrics.boundingRect(0, 0, available_width, 0,
                                                  Qt.TextWordWrap | Qt.AlignLeft | Qt.AlignTop, text)
            num_lines = max(1, int((text_rect.height() + line_height - 1) / line_height))
            label_widget.setMinimumHeight(line_height * num_lines + 4)
        
        def _dir_display_name(p):
            """Basename for display; handles trailing slash (e.g. /Users/foo/ -> foo)."""
            if not p:
                return ""
            return os.path.basename((p or "").rstrip("/") or ".") or "."

        def update_dir_label():
            if dir_checkbox.isChecked():
                try:
                    is_recursive = recursive_checkbox.isChecked()
                except NameError:
                    is_recursive = getattr(dialog, 'recursive_checkbox', None)
                    if is_recursive:
                        is_recursive = is_recursive.isChecked()
                    else:
                        is_recursive = False
                path = dir_input.text().strip()
                resolved = _resolved_dir_input()
                if path and resolved and os.path.isdir(resolved):
                    name = _dir_display_name(resolved)
                    if is_recursive:
                        dir_label.setText(f"Search {name} and its subdirectories")
                    else:
                        dir_label.setText(f"Search {name}")
                elif directory:
                    name = _dir_display_name(directory)
                    if is_recursive:
                        dir_label.setText(f"Search {name} and its subdirectories")
                    else:
                        dir_label.setText(f"Search {name}")
                else:
                    dir_label.setText("Find images containing the selected person")
                _update_label_height(dir_label)
            else:
                search_dir = None
                if directory and os.path.isdir(directory):
                    search_dir = directory
                elif self.parent_widget and hasattr(self.parent_widget, 'get_current_search_directory'):
                    search_dir = self.parent_widget.get_current_search_directory()
                try:
                    is_recursive = recursive_checkbox.isChecked()
                except NameError:
                    is_recursive = getattr(dialog, 'recursive_checkbox', None)
                    if is_recursive:
                        is_recursive = is_recursive.isChecked()
                    else:
                        is_recursive = False
                if is_recursive and search_dir:
                    name = _dir_display_name(search_dir)
                    dir_label.setText(f"Search in displayed files and files in {name}")
                else:
                    dir_label.setText("Search in displayed files")
                _update_label_height(dir_label)
        
        def update_dir_field_state():
            enabled = dir_checkbox.isChecked()
            dir_input.setEnabled(enabled)
            validation_label.setEnabled(enabled)
            if enabled:
                validate_directory()
                path = dir_input.text().strip()
                resolved = _resolved_dir_input()
                if path and resolved and os.path.isdir(resolved):
                    has_subs = self._has_subdirectories(resolved)
                    if hasattr(dialog, 'recursive_checkbox'):
                        if not has_subs:
                            dialog.recursive_checkbox.setEnabled(False)
                            dialog.recursive_checkbox.setChecked(False)
                        else:
                            dialog.recursive_checkbox.setEnabled(True)
            else:
                displayed_dir = self._get_displayed_files_directory()
                if (not displayed_dir) and self.parent_widget and hasattr(self.parent_widget, 'get_current_search_directory'):
                    displayed_dir = self.parent_widget.get_current_search_directory()
                if (not displayed_dir) and directory and os.path.isdir(directory):
                    displayed_dir = directory
                if displayed_dir and os.path.isdir(displayed_dir):
                    has_subs = self._has_subdirectories(displayed_dir)
                    if hasattr(dialog, 'recursive_checkbox'):
                        if not has_subs:
                            dialog.recursive_checkbox.setEnabled(False)
                            dialog.recursive_checkbox.setChecked(False)
                        else:
                            dialog.recursive_checkbox.setEnabled(True)
            update_dir_label()
            validate_directory()
        
        def update_recursive_state(checked):
            update_dir_label()
            validate_directory()
        
        def check_recursive_enable():
            path = dir_input.text().strip()
            resolved = _resolved_dir_input()
            if dir_checkbox.isChecked() or (path and resolved and os.path.isdir(resolved)):
                if path and resolved and os.path.isdir(resolved):
                    has_subs = self._has_subdirectories(resolved)
                    if not has_subs:
                        recursive_checkbox.setEnabled(False)
                        recursive_checkbox.setChecked(False)
                    else:
                        recursive_checkbox.setEnabled(True)
                else:
                    recursive_checkbox.setEnabled(True)
            else:
                displayed_dir = self._get_displayed_files_directory()
                if (not displayed_dir) and self.parent_widget and hasattr(self.parent_widget, 'get_current_search_directory'):
                    displayed_dir = self.parent_widget.get_current_search_directory()
                if (not displayed_dir) and directory and os.path.isdir(directory):
                    displayed_dir = directory
                if displayed_dir and os.path.isdir(displayed_dir):
                    has_subs = self._has_subdirectories(displayed_dir)
                    if not has_subs:
                        recursive_checkbox.setEnabled(False)
                        recursive_checkbox.setChecked(False)
                    else:
                        recursive_checkbox.setEnabled(True)
                else:
                    recursive_checkbox.setEnabled(True)
        
        browse_button.clicked.connect(browse_directory)
        dir_input.textChanged.connect(lambda: (validate_directory(), update_dir_label(), check_recursive_enable()))
        dir_checkbox.toggled.connect(update_dir_field_state)
        
        layout.addWidget(container)
        
        # Recursive checkbox
        if self.config:
            settings = self.config.load_settings()
            max_depth = settings.get('search_depth', 4)
        else:
            max_depth = 4
        recursive_checkbox = QCheckBox(f"Recursive (search up to {max_depth} directories deep)")
        recursive_checkbox.setToolTip(f"If checked, searches recursively in subdirectories (up to {max_depth} levels)\nand opens results in a new level.\nDepth is controlled by 'Search depth' in the Directories settings tab.")
        recursive_checkbox.setChecked(saved_recursive)
        layout.addWidget(recursive_checkbox)
        recursive_checkbox.toggled.connect(update_recursive_state)
        
        # Buttons
        button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        button_box.accepted.connect(dialog.accept)
        button_box.rejected.connect(dialog.reject)
        layout.addWidget(button_box)
        
        dialog.recursive_checkbox = recursive_checkbox
        dialog.dir_checkbox = dir_checkbox
        dialog.dir_input = dir_input
        dialog.validation_label = validation_label
        dialog.combo = combo
        dialog.ids = ids
        
        update_person_thumbs()
        
        check_recursive_enable()
        update_dir_field_state()
        update_recursive_state(saved_recursive)
        
        if combo:
            combo.setFocus()
        ok_button = button_box.button(QDialogButtonBox.Ok)
        if ok_button:
            ok_button.setDefault(True)
        
        return dialog
    
    def create_similarity_progress_dialog(self, displayed_images_count, is_first_search=False, recursive=False, search_directory=None):
        """Create and configure progress dialog for similarity search
        
        Args:
            displayed_images_count: Number of images to search
            is_first_search: Whether this is the first search (for initialization message)
            recursive: Whether search is recursive
            search_directory: Directory being searched (if checkbox was checked)
        """
        QtCore = _import_qt_modules()[1]
        if QtCore is None:
            raise ImportError("PySide6.QtCore is required for UI components")
        Qt = QtCore['Qt']
        
        # Build label text based on search parameters
        if search_directory and os.path.isdir(search_directory):
            if recursive:
                label_text = f"Searching {os.path.basename(search_directory)} and its subdirectories..."
            else:
                label_text = f"Searching {os.path.basename(search_directory)}..."
        elif recursive:
            # Recursive but no specific directory - use current directory
            if self.parent_widget and hasattr(self.parent_widget, 'get_current_search_directory'):
                current_dir = self.parent_widget.get_current_search_directory()
                if current_dir:
                    label_text = f"Searching displayed files and files in {os.path.basename(current_dir)}..."
                else:
                    label_text = "Searching displayed files and subdirectories..."
            else:
                label_text = "Searching displayed files and subdirectories..."
        else:
            label_text = "Searching displayed files..."
        
        progress_dialog = ProgressDialogWithStatus(
            label_text,
            "Cancel",
            0,
            displayed_images_count,
            self.parent_widget,
            window_title="Search for Similar Images",
        )
        progress_dialog.setWindowModality(Qt.WindowModal)
        progress_dialog.setAutoClose(False)
        progress_dialog.setAutoReset(False)
        progress_dialog.setMinimumDuration(300)  # show at least this fast
        progress_dialog.setValue(0)
        # Show warning on first initialization
        if is_first_search:
            progress_dialog.setStatusText("Initializing... first time may be slow")
        else:
            progress_dialog.setStatusText("Initializing...")
        progress_dialog.show()
        return progress_dialog
    
    def create_clip_progress_dialog(self, text_prompt, displayed_images_count, is_first_search=False, recursive=False, search_directory=None):
        """Create and configure progress dialog for CLIP search
        
        Args:
            text_prompt: Text prompt being searched for
            displayed_images_count: Number of images to search
            is_first_search: Whether this is the first search (for initialization message)
            recursive: Whether search is recursive
            search_directory: Directory being searched (if checkbox was checked)
        """
        QtCore = _import_qt_modules()[1]
        if QtCore is None:
            raise ImportError("PySide6.QtCore is required for UI components")
        Qt = QtCore['Qt']
        
        # Build label text based on search parameters
        if search_directory and os.path.isdir(search_directory):
            if recursive:
                label_text = f"Searching '{text_prompt}' in {os.path.basename(search_directory)} and its subdirectories..."
            else:
                label_text = f"Searching '{text_prompt}' in {os.path.basename(search_directory)}..."
        elif recursive:
            # Recursive but no specific directory - use current directory
            if self.parent_widget and hasattr(self.parent_widget, 'get_current_search_directory'):
                current_dir = self.parent_widget.get_current_search_directory()
                if current_dir:
                    label_text = f"Searching '{text_prompt}' in displayed files and files in {os.path.basename(current_dir)}..."
                else:
                    label_text = f"Searching '{text_prompt}' in displayed files and subdirectories..."
            else:
                label_text = f"Searching '{text_prompt}' in displayed files and subdirectories..."
        else:
            label_text = f"Searching '{text_prompt}' in displayed files..."
        
        progress_dialog = ProgressDialogWithStatus(
            label_text,
            "Cancel",
            0,
            displayed_images_count,
            self.parent_widget,
            window_title="Search by Text",
        )
        progress_dialog.setWindowModality(Qt.WindowModal)
        progress_dialog.setAutoClose(False)
        progress_dialog.setAutoReset(False)
        progress_dialog.setMinimumDuration(300)  # show at least this fast
        progress_dialog.setValue(0)
        # Show warning on first initialization
        if is_first_search:
            progress_dialog.setStatusText("Initializing... first time may be slow")
        else:
            progress_dialog.setStatusText("Initializing...")
        progress_dialog.show()
        return progress_dialog
    
    def create_similarity_progress_callback(self, progress_dialog, is_first_search=False, progress_tracker=None):
        """Create progress callback function for similarity search
        
        Args:
            progress_dialog: Progress dialog instance
            is_first_search: Whether this is the first search
            progress_tracker: Optional StagedProgressTracker instance (created after cache counting)
        """
        # Create timing tracker for fallback callback behavior
        timing_tracker = _TimingTracker()
        
        def progress_cb(*args):
            # Use staged tracker if available
            if progress_tracker is not None:
                if len(args) == 1 and isinstance(args[0], float):
                    progress_tracker.complete()
                    progress_dialog.setStatusText("Finishing up...")
                elif len(args) >= 2 and isinstance(args[0], int) and isinstance(args[1], int):
                    idx, total = args[0], args[1]
                    stage = args[2] if len(args) > 2 else None
                    
                    if stage == "loading_model":
                        progress_tracker.update_model_loading()
                    elif stage == "examining_images":
                        if is_first_search:
                            progress_dialog.setStatusText("Extracting and caching features... first time may be slow")
                        else:
                            progress_dialog.setStatusText("Extracting and caching features...")
                        progress_tracker.update_feature_extraction(idx, total)
                    elif stage == "comparing_images":
                        progress_tracker.update_comparison()
                    else:
                        # Fallback for unknown stages
                        progress_dialog.setValue(idx)
                        progress_dialog.setStatusText(f"Processing image {idx} of {total}...")
                # If user cancels, abort (by raising); handle in CNN code
                if progress_dialog.wasCanceled():
                    raise KeyboardInterrupt("User canceled similarity calculation")
                return
            
            # Fallback to old behavior if no tracker
            if len(args) == 1 and isinstance(args[0], float):
                progress_dialog.setValue(int(args[0] * progress_dialog.maximum))
                progress_dialog.setStatusText("Finishing up...")
                progress_dialog.setFilesRemaining(text="comparing")
            elif len(args) >= 2 and isinstance(args[0], int) and isinstance(args[1], int):
                idx, total = args[0], args[1]
                stage = args[2] if len(args) > 2 else None
                progress_dialog.setValue(idx)
                if stage == "loading_model":
                    progress_dialog.setStatusText("Loading CNN model...")
                    progress_dialog.setFilesRemaining()
                    timing_tracker.reset()  # Reset timing when starting extraction
                elif stage == "examining_images":
                    # Only calculate timing when updating UI (every 10 items or at start/end)
                    # This reduces overhead significantly
                    remaining = total - idx
                    should_update_ui = (idx == 0 or idx % 10 == 0 or idx == total - 1)
                    
                    if should_update_ui:
                        # Get time estimate for files remaining line (only when updating UI)
                        time_estimate = timing_tracker.get_time_estimate(idx, total)
                        if is_first_search:
                            base_text = "Extracting and caching features... first time may be slow"
                        else:
                            base_text = "Extracting and caching features..."
                        progress_dialog.setStatusText(base_text)
                        if remaining > 0:
                            progress_dialog.setFilesRemaining(remaining_count=remaining, time_estimate=time_estimate)
                        else:
                            progress_dialog.setFilesRemaining(text="comparing")
                    else:
                        # Still update progress bar but skip timing calculation
                        progress_dialog.setValue(idx)
                elif stage == "comparing_images":
                    progress_dialog.setStatusText("Calculating similarities and sorting results...")
                    progress_dialog.setFilesRemaining(text="comparing")
                else:
                    progress_dialog.setStatusText(f"Processing image {idx} of {total}...")
                    remaining = total - idx
                    progress_dialog.setFilesRemaining(remaining_count=remaining if remaining > 0 else None)
            if progress_dialog.wasCanceled():
                raise KeyboardInterrupt("User canceled similarity calculation")
        return progress_cb
    
    def create_clip_progress_callback(self, progress_dialog, is_first_search=False, progress_tracker=None):
        """Create progress callback function for CLIP search
        
        Args:
            progress_dialog: Progress dialog instance
            is_first_search: Whether this is the first search
            progress_tracker: Optional StagedProgressTracker instance (created after cache counting)
        """
        # Create timing tracker for fallback callback behavior
        timing_tracker = _TimingTracker()
        
        def progress_cb(idx, total, stage=None):
            # Use staged tracker if available
            if progress_tracker is not None:
                if stage == "loading_model":
                    progress_tracker.update_model_loading()
                    progress_dialog.setStatusText("Loading CLIP model (this may take a moment on first use)...")
                elif stage == "examining_images":
                    if is_first_search:
                        progress_dialog.setStatusText("Extracting and caching features... first time may be slow")
                    else:
                        progress_dialog.setStatusText("Extracting and caching features...")
                    progress_tracker.update_feature_extraction(idx, total)
                elif stage == "comparing_images":
                    progress_tracker.update_comparison()
                else:
                    progress_dialog.setStatusText("Initializing search...")
                    progress_dialog.setValue(idx)
                if progress_dialog.wasCanceled():
                    raise KeyboardInterrupt("User canceled Find Images search")
                return
            
            # Fallback to old behavior if no tracker
            # Update UI only on 1st (idx == 0) and every 10th displayed number (10, 20, 30...), or last item
            # Use (idx + 1) % 10 == 0 to match displayed numbers 10, 20, 30, etc.
            should_update_ui = (idx == 0 or (idx + 1) % 10 == 0 or idx == total - 1)
            
            if should_update_ui:
                progress_dialog.setValue(idx)
                if stage == "loading_model":
                    progress_dialog.setStatusText("Loading CLIP model (this may take a moment on first use)...")
                    progress_dialog.setFilesRemaining()
                    timing_tracker.reset()  # Reset timing when starting extraction
                elif stage == "examining_images":
                    # Get time estimate for files remaining line
                    time_estimate = timing_tracker.get_time_estimate(idx, total)
                    if is_first_search:
                        base_text = "Extracting and caching features... first time may be slow"
                    else:
                        base_text = "Extracting and caching features..."
                    progress_dialog.setStatusText(base_text)
                    remaining = total - idx
                    if remaining > 0:
                        progress_dialog.setFilesRemaining(remaining_count=remaining, time_estimate=time_estimate)
                    else:
                        progress_dialog.setFilesRemaining(text="comparing")
                elif stage == "comparing_images":
                    progress_dialog.setStatusText("Calculating similarities and sorting results...")
                    progress_dialog.setFilesRemaining(text="comparing")
                else:
                    progress_dialog.setStatusText("Initializing search...")
                    remaining = total - idx
                    progress_dialog.setFilesRemaining(remaining_count=remaining if remaining > 0 else None)
            
            if progress_dialog.wasCanceled():
                raise KeyboardInterrupt("User canceled Find Images search")
        return progress_cb
    
    def mark_similarity_search_used(self):
        """Mark that similarity search has been used (for first-time warnings)"""
        self._first_similarity_search = False
    
    def mark_clip_search_used(self):
        """Mark that CLIP search has been used (for first-time warnings)"""
        self._first_clip_search = False
    
    @property
    def is_first_similarity_search(self):
        """Check if this is the first similarity search"""
        return self._first_similarity_search
    
    @property
    def is_first_clip_search(self):
        """Check if this is the first CLIP search"""
        return self._first_clip_search

def _is_inside_macos_trash(path):
    """
    Returns True if the path is under a .Trashes directory on macOS, else False.
    This excludes any files in .../.Trashes/ or ~/.Trash/
    """
    # Normalize to absolute path to work with os.path components
    path = os.path.abspath(path)
    # Standard .Trashes for volumes or drives
    if any(part == '.Trashes' for part in path.split(os.sep)):
        return True
    # User Trash folder
    user_trash = os.path.expanduser('~/.Trash')
    if path.startswith(user_trash + os.sep) or path == user_trash:
        return True
    return False



class CNNImageSimilaritySorter:
    def __init__(self, device=None, similarity_metric='cosine', cache_dir=None, clip_model_name=None, resnet_model=None):
        # Reference to main_window for background process coordination (set after initialization)
        self.main_window = None
        """
        Initialize CNN-based image similarity sorter.
        
        Args:
            device: Torch device ('mps', 'cuda', 'cpu', or None for auto-detection)
            similarity_metric: Metric to use for similarity comparison.
                              Options: 'cosine', 'euclidean', 'manhattan'
                              Default: 'cosine'
            cache_dir: Optional cache directory path (default: from config)
            clip_model_name: CLIP model name to use (default: from config)
            resnet_model: ResNet model name to use ('resnet18', 'resnet50', 'resnet101', default: from config)
        """
        # Store parameters for lazy initialization
        self._device_param = device
        self.similarity_metric = similarity_metric
        
        # Validate similarity metric
        valid_metrics = ['cosine', 'euclidean', 'manhattan']
        if similarity_metric not in valid_metrics:
            print(f"Warning: Invalid similarity metric '{similarity_metric}'. Using 'cosine' instead.")
            self.similarity_metric = 'cosine'
        
        # Get clip_model_name from config if not provided
        if clip_model_name is None:
            from config import get_config
            config = get_config()
            settings = config.load_settings()
            clip_model_name = settings.get('clip_model_name', 'openai/clip-vit-base-patch32')
        
        # Try to locate cached safetensors file for this model
        base_hf_dir = os.path.expanduser("~/.cache/huggingface/hub")
        model_dir_pattern = f"models--{clip_model_name.replace('/', '--')}"
        search_path = os.path.join(base_hf_dir, model_dir_pattern, "snapshots", "*", "model.safetensors")
        candidate_paths = glob.glob(search_path)
        
        # Validate cached model directories - check for required files
        clip_model_path = clip_model_name  # Default fallback
        if candidate_paths:
            for candidate_path in candidate_paths:
                candidate_dir = os.path.dirname(candidate_path)
                # Check for required files: preprocessor_config.json (for processor) and config.json (for model)
                preprocessor_config = os.path.join(candidate_dir, "preprocessor_config.json")
                model_config = os.path.join(candidate_dir, "config.json")
                if os.path.exists(preprocessor_config) and os.path.exists(model_config):
                    # This directory has all required files, use it
                    clip_model_path = candidate_dir
                    break
            # If we found candidates but none were valid, fall back to model name
            # (transformers will handle downloading/loading properly)
        
        self._clip_model_name_param = clip_model_path
        from config import get_config
        if get_config().load_settings().get('debug_mode', False):
            print(f"We are using CLIP model from {clip_model_path}")
        
        # Get resnet_model from config if not provided
        if resnet_model is None:
            from config import get_config
            config = get_config()
            settings = config.load_settings()
            resnet_model = settings.get('resnet_model', 'resnet18')
        
        # Try to locate local weights file for this model (prefer local file for performance)
        resnet_to_filename = {
            'resnet18':   'resnet18-*.pth',
            'resnet50':   'resnet50-*.pth',
            'resnet101':  'resnet101-*.pth',
        }
        local_model_path = None
        local_model_base = None

        # If user provided a full path to a weights file, allow that.
        if os.path.isfile(str(resnet_model)):
            # Try to detect which resnet model this file is for from the filename
            filename = os.path.basename(str(resnet_model)).lower()
            model_type = None
            for key in resnet_to_filename.keys():
                if key in filename:
                    model_type = key
                    break
            if model_type is not None:
                local_model_base = model_type
                local_model_path = str(resnet_model)
                if get_config().load_settings().get('debug_mode', False):
                    print(f"Using local ResNet weights from {local_model_path} (model type: {local_model_base})")
            else:
                # If nothing matches, fallback to configured or default model
                print(f"Warning: Unknown resnet_model file '{resnet_model}'. Using resnet18 instead.")
                local_model_base = 'resnet18'
                local_model_path = None
                if get_config().load_settings().get('debug_mode', False):
                    print(f"Using ResNet model: {local_model_base} (default weights)")
        elif resnet_model in resnet_to_filename:
            # Try to find a local weights file for this model
            base_torch_dir = os.path.expanduser("~/.cache/torch/hub/checkpoints")
            search_pattern = os.path.join(base_torch_dir, resnet_to_filename[resnet_model])
            candidate_weights = glob.glob(search_pattern)
            if candidate_weights:
                # Use the first found local weights file path
                local_model_path = candidate_weights[0]
                local_model_base = resnet_model
                if get_config().load_settings().get('debug_mode', False):
                    print(f"Using local ResNet weights from {local_model_path} (model type: {local_model_base})")
            else:
                local_model_base = resnet_model
                local_model_path = None
                if get_config().load_settings().get('debug_mode', False):
                    print(f"Using ResNet model: {local_model_base} (default weights)")
        else:
            # Unknown string - fallback to resnet18 as before
            print(f"Warning: Unknown resnet_model '{resnet_model}'. Using resnet18 instead.")
            local_model_base = 'resnet18'
            local_model_path = None
            if get_config().load_settings().get('debug_mode', False):
                print(f"Using ResNet model: {local_model_base} (default weights)")

        # These params: base model type and optional local path for weights (not model/weights as a pair)
        self._resnet_model_base = local_model_base
        self._resnet_model_weights_path = local_model_path
        # For compatibility with previous code (until all uses are updated):
        self._resnet_model_param = resnet_model
        
        # Lazy initialization flags
        self._model_loaded = False
        self.device = None
        self.model = None
        self.feature_extractor = None
        self.transform = None
        
        # CLIP model initialization (lazy loading - always available if transformers is installed)
        self.clip_model = None
        self.clip_processor = None
        self._clip_loaded = False
        self.clip_model_name = None
        self.clip_feature_dim = None  # Expected feature dimension for current model
        
        # Use configured image extensions from settings (supports .jpg, .jpeg, .png, .webp, .heic, .heif, etc.)
        from thumbnails.thumbnail_constants import get_image_extensions
        self.extensions = tuple(get_image_extensions())
        
        # Initialize persistent feature cache manager (but don't load cache yet)
        self._cache_dir = cache_dir
        self.feature_cache = None  # Will be initialized lazily when needed

        # In-memory caches for current session (backed by persistent cache)
        # Per-path feature cache: {path: (feature_vector or None if failed, mtime, size)}
        self._feature_cache = {}
        # CLIP image feature cache: {path: (feature_vector or None if failed, mtime, size)}
        self._clip_feature_cache = {}
        # For safety, track the candidates set from last run so we can evict features for vanished images.
        self._last_candidates_set = None
        self._last_sorted = None
    
    def _ensure_model_loaded(self):
        """Lazy load torch modules and ResNet model (selected by resnet_model parameter)"""
        if self._model_loaded:
            return
        
        # Import torch modules
        torch, F, transforms, models, ResNet18_Weights, ResNet50_Weights, ResNet101_Weights = _import_torch_modules()
        
        # Device selection: Prefer MPS (Apple Silicon GPU), then CUDA, then CPU
        if self._device_param:
            self.device = self._device_param
        elif hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            self.device = "mps"
        elif torch.cuda.is_available():
            self.device = "cuda"
        else:
            self.device = "cpu"

        # Select ResNet model based on resnet_model parameter
        model_name = self._resnet_model_param.lower()
        if model_name == 'resnet18':
            self.model = models.resnet18(weights=ResNet18_Weights.DEFAULT)
        elif model_name == 'resnet50':
            self.model = models.resnet50(weights=ResNet50_Weights.DEFAULT)
        elif model_name == 'resnet101':
            self.model = models.resnet101(weights=ResNet101_Weights.DEFAULT)
        else:
            print(f"Warning: Unknown resnet_model '{self._resnet_model_param}'. Using resnet18 instead.")
            self.model = models.resnet18(weights=ResNet18_Weights.DEFAULT)
        
        self.model = self.model.to(self.device)
        self.model.eval()
        # Remove last linear layer (get feature vectors instead of class logits)
        self.feature_extractor = torch.nn.Sequential(*(list(self.model.children())[:-1]))
        self.feature_extractor.eval()
        for p in self.feature_extractor.parameters():
            p.requires_grad = False

        # Standard preprocessing
        self.transform = transforms.Compose([
            transforms.Resize(256),
            transforms.CenterCrop(224),
            transforms.Lambda(lambda img: img.convert('RGB')), # in case of 'L' mode or RGBA
            transforms.ToTensor(),
            transforms.Normalize(
                mean=[0.485, 0.456, 0.406],
                std=[0.229, 0.224, 0.225]
            ),
        ])
        
        self._model_loaded = True
    

    def unload_models(self):
        """Unload CNN and CLIP models from memory to free GPU/RAM"""
        import torch
        
        cnn_was_loaded = self._model_loaded
        clip_was_loaded = self._clip_loaded
        
        # Calculate memory usage before unloading
        total_memory_bytes = 0
        cnn_memory_mb = 0.0
        clip_memory_mb = 0.0
        
        if self._model_loaded and self.model is not None:
            try:
                # Calculate CNN model memory (sum of all parameter sizes)
                cnn_params = sum(p.numel() * p.element_size() for p in self.model.parameters())
                cnn_memory_bytes = cnn_params
                cnn_memory_mb = cnn_memory_bytes / (1024 * 1024)
                total_memory_bytes += cnn_memory_bytes
            except Exception as e:
                print(f"Error calculating CNN model memory: {e}")
        
        if self._clip_loaded and self.clip_model is not None:
            try:
                # Calculate CLIP model memory (sum of all parameter sizes)
                clip_params = sum(p.numel() * p.element_size() for p in self.clip_model.parameters())
                clip_memory_bytes = clip_params
                clip_memory_mb = clip_memory_bytes / (1024 * 1024)
                total_memory_bytes += clip_memory_bytes
            except Exception as e:
                print(f"Error calculating CLIP model memory: {e}")
        
        total_memory_mb = total_memory_bytes / (1024 * 1024)
        
        # Unload CNN model
        if self._model_loaded:
            if self.model is not None:
                del self.model
            if self.feature_extractor is not None:
                del self.feature_extractor
            self.model = None
            self.feature_extractor = None
            self._model_loaded = False
        
        # Unload CLIP model
        if self._clip_loaded:
            if self.clip_model is not None:
                del self.clip_model
            if self.clip_processor is not None:
                del self.clip_processor
            self.clip_model = None
            self.clip_processor = None
            self._clip_loaded = False
        
        # Clear GPU cache if using CUDA or MPS
        if self.device and self.device != 'cpu':
            try:
                if self.device == 'cuda':
                    torch.cuda.empty_cache()
                elif self.device == 'mps':
                    torch.mps.empty_cache()
            except Exception as e:
                pass  # Ignore errors clearing cache
        
        if cnn_was_loaded or clip_was_loaded:
            from config import get_config
            if get_config().load_settings().get('debug_mode', False):
                memory_info = []
                if cnn_was_loaded:
                    memory_info.append(f"CNN={cnn_memory_mb:.1f}MB")
                if clip_was_loaded:
                    memory_info.append(f"CLIP={clip_memory_mb:.1f}MB")
                memory_str = ", ".join(memory_info)
                print(f"Unloaded models ({memory_str}): total memory freed={total_memory_mb:.1f}MB")

    def _ensure_feature_cache_loaded(self):
        """Lazy load feature cache manager"""
        if self.feature_cache is None:
            try:
                from cache.feature_cache_manager import FeatureCacheManager
                if self._cache_dir:
                    from pathlib import Path
                    self.feature_cache = FeatureCacheManager(
                        cache_dir=Path(self._cache_dir),
                        clip_model_name=self._clip_model_name_param,
                        resnet_model_name=self._resnet_model_param,
                        sorter_reference=self
                    )
                else:
                    self.feature_cache = FeatureCacheManager(
                        clip_model_name=self._clip_model_name_param,
                        resnet_model_name=self._resnet_model_param,
                        sorter_reference=self
                    )
            except Exception as e:
                print(f"Warning: Could not initialize feature cache: {e}")
                self.feature_cache = None

    def _get_mtime_size(self, path):
        try:
            stat = os.stat(path)
            return (stat.st_mtime, stat.st_size)
        except Exception as e:
            print(f"Error getting mtime and size for {path}: {e}")
            import traceback
            traceback.print_exc()
            return (None, None)

    def _is_feature_cached(self, path):
        """Check if CNN feature is cached without retrieving it"""
        self._ensure_feature_cache_loaded()
        
        mtime, size = self._get_mtime_size(path)
        if mtime is None or size is None:
            return False
        
        # Check in-memory cache first
        if path in self._feature_cache:
            feat, cached_mtime, cached_size = self._feature_cache[path]
            if (cached_mtime == mtime) and (cached_size == size):
                return True
        
        # Check persistent cache
        if self.feature_cache:
            cached_feat = self.feature_cache.get_cnn_feature(path, mtime, size, device='cpu')
            if cached_feat is not None:
                return True
        
        return False

    def _is_clip_feature_cached(self, path):
        """Check if CLIP feature is cached without retrieving it"""
        self._ensure_feature_cache_loaded()
        
        mtime, size = self._get_mtime_size(path)
        if mtime is None or size is None:
            return False
        
        # Check in-memory cache first
        if path in self._clip_feature_cache:
            feat, cached_mtime, cached_size = self._clip_feature_cache[path]
            if (cached_mtime == mtime) and (cached_size == size) and feat is not None:
                # If model is loaded, verify feature dimension matches current model
                if self._clip_loaded and self.clip_feature_dim is not None:
                    if feat.shape[0] == self.clip_feature_dim:
                        return True
                else:
                    # Model not loaded yet, but we have a cached feature - assume it's valid
                    # (will be validated when model loads)
                    return True
        
        # Check persistent cache
        if self.feature_cache:
            cached_feat = self.feature_cache.get_clip_feature(path, mtime, size, device='cpu')
            if cached_feat is not None:
                # If model is loaded, verify feature dimension matches current model
                if self._clip_loaded and self.clip_feature_dim is not None:
                    if cached_feat.shape[0] == self.clip_feature_dim:
                        return True
                else:
                    # Model not loaded yet, but we have a cached feature - assume it's valid
                    # (will be validated when model loads and _get_clip_image_feature is called)
                    return True
        
        return False

    def _load_image(self, path):
        """Load and transform image"""
        self._ensure_model_loaded()
        _ensure_heif_opener()
        try:
            # Try PIL first (fast path for most formats)
            with Image.open(path) as img:
                return self.transform(img)
        except Exception as pil_error:
            # PIL failed - check if it's a format PIL can't handle (like HEIC)
            error_msg = str(pil_error).lower()
            if 'cannot identify' in error_msg or 'cannot open' in error_msg:
                _ensure_heif_opener()
                try:
                    with Image.open(path) as img:
                        return self.transform(img)
                except Exception:
                    pass
                # Try Qt's QImage as fallback (can handle HEIC on macOS)
                try:
                    from PySide6.QtGui import QImage
                    from PySide6.QtCore import QBuffer, QIODevice
                    import io
                    
                    qimage = QImage(path)
                    if qimage.isNull():
                        return None
                    
                    # Convert QImage to PIL Image via QBuffer
                    buffer = QBuffer()
                    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
                    if not qimage.save(buffer, format='PNG'):
                        return None
                    buffer.close()
                    
                    # Load from buffer with PIL
                    pil_buffer = io.BytesIO(buffer.data())
                    pil_img = Image.open(pil_buffer)
                    if pil_img.mode != 'RGB':
                        pil_img = pil_img.convert('RGB')
                    return self.transform(pil_img)
                except Exception:
                    return None
            else:
                # Some other PIL error
                return None

    def _get_feature(self, path):
        """Get CNN feature for an image path (with caching)"""
        self._ensure_model_loaded()
        self._ensure_feature_cache_loaded()
        
        torch, F, transforms, models, ResNet18_Weights, ResNet50_Weights, ResNet101_Weights = _import_torch_modules()
        
        # Get mtime and size for cache key checking
        mtime, size = self._get_mtime_size(path)

        # Check in-memory cache first
        cache_hit = False
        if path in self._feature_cache:
            feat, cached_mtime, cached_size = self._feature_cache[path]
            if (cached_mtime == mtime) and (cached_size == size):
                cache_hit = True
        if cache_hit:
            # Ensure feature is on the correct device
            if feat is not None and feat.device.type != self.device:
                feat = feat.to(self.device)
            return feat
        
        # Check persistent cache
        if self.feature_cache and mtime is not None and size is not None:
            cached_feat = self.feature_cache.get_cnn_feature(path, mtime, size, device=self.device)
            if cached_feat is not None:
                # Store in memory cache for faster access
                self._feature_cache[path] = (cached_feat, mtime, size)
                return cached_feat
        
        # Cache miss or file changed: recalc
        image_tensor = self._load_image(path)
        if image_tensor is None:
            self._feature_cache[path] = (None, mtime, size)
            if self.feature_cache:
                self.feature_cache.set_cnn_feature(path, None, mtime, size)
            return None
        image_tensor = image_tensor.unsqueeze(0).to(self.device)
        with torch.no_grad():
            feat = self.feature_extractor(image_tensor)
            feat = feat.view(feat.size(0), -1)
        feat = feat.squeeze(0)
        
        # Store in both caches
        self._feature_cache[path] = (feat, mtime, size)
        if self.feature_cache and mtime is not None and size is not None:
            self.feature_cache.set_cnn_feature(path, feat, mtime, size)
        
        return feat

    def _load_clip_model(self):
        """Lazy load CLIP model if available"""
        if self._clip_loaded:
            return
        
        self._ensure_model_loaded()  # Need device for CLIP model
        self._ensure_feature_cache_loaded()
        
        CLIP_AVAILABLE, CLIPProcessor, CLIPModel = _import_clip_modules()
        
        if not CLIP_AVAILABLE:
            print("ERROR: CLIP requested but transformers library not available.")
            print("Install with: pip install transformers")
            print("Or activate your virtual environment if transformers is installed there.")
            return
        
        try:
            # Use the model name from parameter (which comes from settings)
            model_name = self._clip_model_name_param
            print(f"Loading CLIP model {model_name}")

            # Use a smaller model for better performance: openai/clip-vit-base-patch32
            # This will auto-download if not cached
            self.clip_model = CLIPModel.from_pretrained(model_name)
            self.clip_processor = CLIPProcessor.from_pretrained(model_name, use_fast=True)
            self.clip_model = self.clip_model.to(self.device)
            self.clip_model.eval()
            for p in self.clip_model.parameters():
                p.requires_grad = False
            self.clip_model_name = model_name
            # Get expected feature dimension from model config
            self.clip_feature_dim = self.clip_model.config.projection_dim
            self._clip_loaded = True
        except Exception as e:
            import traceback
            print(f"ERROR loading CLIP model {model_name}: {e}")
            print("Full traceback:")
            traceback.print_exc()
            self.clip_model = None
            self.clip_processor = None
            self.clip_model_name = None
            self.clip_feature_dim = None

    def _get_clip_text_features(self, text_prompt):
        """Get CLIP text features for a prompt"""
        if not self._clip_loaded:
            self._load_clip_model()
        
        if not self._clip_loaded or self.clip_model is None or self.clip_processor is None:
            raise RuntimeError("CLIP model not available")
        
        torch, F, transforms, models, ResNet18_Weights, ResNet50_Weights, ResNet101_Weights = _import_torch_modules()
        
        try:
            inputs = self.clip_processor(text=[text_prompt], return_tensors="pt", padding=True, truncation=True)
            inputs = {k: v.to(self.device) for k, v in inputs.items()}
            
            with torch.no_grad():
                # Try get_text_features() first (most direct method)
                if hasattr(self.clip_model, 'get_text_features'):
                    text_output = self.clip_model.get_text_features(**inputs)
                    # get_text_features should return a tensor directly
                    if isinstance(text_output, torch.Tensor):
                        text_features = text_output
                    else:
                        # If it returns an output object, extract text_embeds
                        if hasattr(text_output, 'text_embeds'):
                            text_features = text_output.text_embeds
                        elif hasattr(text_output, 'pooler_output'):
                            text_features = text_output.pooler_output
                        else:
                            raise ValueError(f"get_text_features returned unexpected type: {type(text_output)}")
                else:
                    # Fallback: use text_model directly (for older versions or if get_text_features doesn't exist)
                    if hasattr(self.clip_model, 'text_model'):
                        text_outputs = self.clip_model.text_model(**inputs)
                        # Get the pooled output
                        if hasattr(text_outputs, 'pooler_output'):
                            pooled_output = text_outputs.pooler_output
                        elif hasattr(text_outputs, 'last_hidden_state'):
                            # Use mean pooling if pooler_output not available
                            pooled_output = text_outputs.last_hidden_state.mean(dim=1)
                        else:
                            raise ValueError(f"text_model output has no pooler_output or last_hidden_state: {type(text_outputs)}")
                        
                        # Apply text projection to get final embeddings
                        if hasattr(self.clip_model, 'text_projection'):
                            text_features = self.clip_model.text_projection(pooled_output)
                        else:
                            # If no projection, use pooled output directly
                            text_features = pooled_output
                    else:
                        raise ValueError("CLIP model has neither get_text_features() nor text_model attribute")
                
                # Ensure we have a tensor
                if not isinstance(text_features, torch.Tensor):
                    raise ValueError(f"Could not extract tensor from text output: {type(text_features)}")
                
                # Normalize features for cosine similarity
                text_features = F.normalize(text_features, dim=-1)
            
            return text_features.squeeze(0)
        except Exception as e:
            print(f"Error encoding text prompt '{text_prompt}': {e}")
            import traceback
            traceback.print_exc()
            return None
    def _get_clip_image_feature(self, path):
        """Get CLIP image features for a path (with caching)"""
        if not self._clip_loaded:
            self._load_clip_model()
        
        if not self._clip_loaded or self.clip_model is None or self.clip_processor is None:
            return None
        
        torch, F, transforms, models, ResNet18_Weights, ResNet50_Weights, ResNet101_Weights = _import_torch_modules()
        
        # Get mtime and size for cache key checking
        mtime, size = self._get_mtime_size(path)
        
        # Check in-memory cache first
        cache_hit = False
        if path in self._clip_feature_cache:
            feat, cached_mtime, cached_size = self._clip_feature_cache[path]
            if (cached_mtime == mtime) and (cached_size == size) and feat is not None:
                # Verify feature dimension matches current model
                if self.clip_feature_dim is not None and feat.shape[0] == self.clip_feature_dim:
                    cache_hit = True
                else:
                    # Dimension mismatch - invalidate cache entry
                    del self._clip_feature_cache[path]
        if cache_hit:
            return feat
        
        # Check persistent cache
        if self.feature_cache and mtime is not None and size is not None:
            cached_feat = self.feature_cache.get_clip_feature(path, mtime, size, device=self.device)
            if cached_feat is not None:
                # Verify feature dimension matches current model
                if self.clip_feature_dim is not None and cached_feat.shape[0] == self.clip_feature_dim:
                    # Store in memory cache for faster access
                    self._clip_feature_cache[path] = (cached_feat, mtime, size)
                    return cached_feat
                # Dimension mismatch - cache entry is for different model, ignore it
        
        # Cache miss or file changed: recalc
        try:
            _ensure_heif_opener()
            # Try PIL first (fast path for most formats)
            try:
                with Image.open(path) as pil_img:
                    # Convert to RGB if needed - always create a new image object
                    # to avoid issues when the context manager closes the original
                    if pil_img.mode != 'RGB':
                        img = pil_img.convert('RGB')
                    else:
                        # Create a copy to ensure we have a valid image after context exits
                        img = pil_img.copy()
            except Exception as pil_error:
                # PIL failed - check if it's a format PIL can't handle (like HEIC)
                error_msg = str(pil_error).lower()
                if 'cannot identify' in error_msg or 'cannot open' in error_msg:
                    _ensure_heif_opener()
                    try:
                        with Image.open(path) as pil_img:
                            if pil_img.mode != 'RGB':
                                img = pil_img.convert('RGB')
                            else:
                                img = pil_img.copy()
                    except Exception:
                        img = None
                    if img is None:
                        # Try Qt's QImage as fallback (can handle HEIC on macOS)
                        try:
                            from PySide6.QtGui import QImage
                            from PySide6.QtCore import QBuffer, QIODevice
                            import io
                            
                            qimage = QImage(path)
                            if qimage.isNull():
                                self._clip_feature_cache[path] = (None, mtime, size)
                                if self.feature_cache:
                                    self.feature_cache.set_clip_feature(path, None, mtime, size)
                                return None
                            
                            # Convert QImage to PIL Image via QBuffer
                            buffer = QBuffer()
                            buffer.open(QIODevice.OpenModeFlag.WriteOnly)
                            if not qimage.save(buffer, format='PNG'):
                                self._clip_feature_cache[path] = (None, mtime, size)
                                if self.feature_cache:
                                    self.feature_cache.set_clip_feature(path, None, mtime, size)
                                return None
                            buffer.close()
                            
                            # Load from buffer with PIL
                            pil_buffer = io.BytesIO(buffer.data())
                            img = Image.open(pil_buffer)
                            # Ensure image is fully loaded before buffer goes out of scope
                            img.load()
                            if img.mode != 'RGB':
                                img = img.convert('RGB')
                        except Exception:
                            self._clip_feature_cache[path] = (None, mtime, size)
                            if self.feature_cache:
                                self.feature_cache.set_clip_feature(path, None, mtime, size)
                            return None
                else:
                    # Some other PIL error
                    self._clip_feature_cache[path] = (None, mtime, size)
                    if self.feature_cache:
                        self.feature_cache.set_clip_feature(path, None, mtime, size)
                    return None
            
            # Process with CLIP
            inputs = self.clip_processor(images=img, return_tensors="pt", padding=True)
            inputs = {k: v.to(self.device) for k, v in inputs.items()}
            
            with torch.no_grad():
                image_output = self.clip_model.get_image_features(**inputs)
                # get_image_features may return a tensor directly or an output object
                if isinstance(image_output, torch.Tensor):
                    image_features = image_output
                else:
                    # If it returns an output object, extract image_embeds
                    if hasattr(image_output, 'image_embeds'):
                        image_features = image_output.image_embeds
                    elif hasattr(image_output, 'pooler_output'):
                        image_features = image_output.pooler_output
                    else:
                        raise ValueError(f"get_image_features returned unexpected type: {type(image_output)}")
                # Normalize features for cosine similarity
                image_features = F.normalize(image_features, dim=-1)
            
            feat = image_features.squeeze(0)
            
            # Store in both caches
            self._clip_feature_cache[path] = (feat, mtime, size)
            if self.feature_cache and mtime is not None and size is not None:
                self.feature_cache.set_clip_feature(path, feat, mtime, size)
            
            return feat
        except Exception as e:
            print(f"Error processing image '{path}' with CLIP: {e}")
            import traceback
            traceback.print_exc()
            self._clip_feature_cache[path] = (None, mtime, size)
            if self.feature_cache:
                self.feature_cache.set_clip_feature(path, None, mtime, size)
            return None

    def _evict_vanished_features(self, alive_set):
        # Remove any features for paths that are no longer in any current candidate set,
        # to prevent unbounded memory growth if folder content changes.
        vanished = set(self._feature_cache.keys()) - alive_set
        for k in vanished:
            del self._feature_cache[k]
        
        # Also evict CLIP features
        vanished_clip = set(self._clip_feature_cache.keys()) - alive_set
        for k in vanished_clip:
            del self._clip_feature_cache[k]
        
        # Evict from persistent cache (but keep for future directory switches)
        # Note: We don't evict from persistent cache here to allow cross-directory reuse
        # The persistent cache manager can handle cleanup separately if needed
    def _compute_similarity(self, feat1, feat2):
        """
        Compute similarity between two feature vectors using the configured metric.
        
        Args:
            feat1: First feature vector (reference image)
            feat2: Second feature vector (candidate image)
        
        Returns:
            Similarity score as a float. Higher values indicate more similarity.
            For distance-based metrics (euclidean, manhattan), returns negative distance
            so that higher scores still mean more similarity.
        """
        torch, F, transforms, models, ResNet18_Weights, ResNet50_Weights, ResNet101_Weights = _import_torch_modules()
        
        # Ensure both tensors are on the same device (use self.device as target)
        if feat1.device.type != self.device:
            feat1 = feat1.to(self.device)
        if feat2.device.type != self.device:
            feat2 = feat2.to(self.device)
        
        if self.similarity_metric == 'cosine':
            # Cosine similarity: measures angle between vectors (range: -1 to 1)
            # Higher values indicate more similar vectors
            return F.cosine_similarity(feat1, feat2, dim=0).item()
        
        elif self.similarity_metric == 'euclidean':
            # Euclidean distance: measures straight-line distance between vectors
            # Convert to similarity by negating (higher similarity = lower distance)
            # Normalize by feature dimension to keep values in reasonable range
            distance = torch.norm(feat1 - feat2, p=2).item()
            # Normalize by dividing by approximate max distance (sqrt of feature dim)
            # This keeps similarity scores roughly in [-1, 1] range
            feat_dim = feat1.numel()
            normalized_distance = distance / (feat_dim ** 0.5) if feat_dim > 0 else distance
            return -normalized_distance  # Negate so higher = more similar
        
        elif self.similarity_metric == 'manhattan':
            # Manhattan (L1) distance: sum of absolute differences
            # Convert to similarity by negating (higher similarity = lower distance)
            distance = torch.norm(feat1 - feat2, p=1).item()
            # Normalize by feature dimension
            feat_dim = feat1.numel()
            normalized_distance = distance / feat_dim if feat_dim > 0 else distance
            return -normalized_distance  # Negate so higher = more similar
        
        else:
            # Fallback to cosine similarity if unknown metric
            print(f"Warning: Unknown similarity metric '{self.similarity_metric}'. Using cosine similarity.")
            return F.cosine_similarity(feat1, feat2, dim=0).item()

    def reorder_by_text_prompt(self, displayed_images, text_prompt, progress_callback=None, 
                               similarity_threshold=None, filter_below_threshold=False, progress_dialog=None):
        """
        Reorder images by similarity to a text prompt using CLIP.

        Args:
            displayed_images: List[str] file paths of displayed images
            text_prompt: Text description to search for
            progress_callback: function(float) or function(int, int), optional.
                               Called as progress_callback(completed, total)
            similarity_threshold: Optional minimum similarity score (0.0-1.0) for filtering.
                                  If None, no filtering is applied.
            filter_below_threshold: If True and similarity_threshold is set, exclude images
                                   below threshold. If False, include all but sort by similarity.
        Returns:
            tuple: (List[str], float) - (reordered list, highest similarity score)
                   reordered list is most similar to text_prompt first
                   (only includes matches if filter_below_threshold=True and threshold is set)
                   highest_score is None if no images were scored
        """
        # Pause background CLIP extraction during foreground extraction
        background_was_paused = False
        if (self.main_window and 
            hasattr(self.main_window, 'background_clip_controller') and 
            self.main_window.background_clip_controller and
            self.main_window.background_clip_controller.enabled):
            if self.main_window.background_clip_controller.is_background_active():
                self.main_window.background_clip_controller.pause_process()
                background_was_paused = True
        
        try:
            # Safety: filter for image files that exist and valid extension, and not in .Trashes/.Trash or Photos Library
            # Use set for faster extension checking
            extensions_set = set(self.extensions)
            candidates = [
                p for p in displayed_images
                if isinstance(p, str)
                and os.path.exists(p)
                and os.path.splitext(p.lower())[1] in extensions_set
                and not _is_inside_macos_trash(p)
                and not is_inside_photos_library_resources_or_scopes(p)
            ]
            candidates_set = set(candidates)
            
            # Clean up feature cache for images no longer present
            self._evict_vanished_features(candidates_set)
            
            total = len(candidates)
            if total == 0:
                if progress_callback is not None:
                    try:
                        progress_callback(1.0)
                    except Exception as e:
                        print(f"Error in progress callback (reorder_by_text_prompt): {e}")
                        import traceback
                        traceback.print_exc()
                        pass
                return (displayed_images, None)
            
            # Count cache misses before starting to set accurate progress range
            # Ensure cache is loaded for accurate checking
            self._ensure_feature_cache_loaded()
            
            # Count images that need processing (not cached)
            images_to_process = []
            for path in candidates:
                if not self._is_clip_feature_cached(path):
                    images_to_process.append(path)
            
            # Create staged progress tracker if we have a progress_dialog
            progress_tracker = None
            if progress_dialog is not None:
                progress_tracker = StagedProgressTracker(progress_dialog, len(images_to_process))
            
            # Try to load CLIP model if not already loaded
            if not self._clip_loaded:
                # Notify about model loading stage
                if progress_tracker is not None:
                    progress_tracker.update_model_loading("Loading CLIP model (this may take a moment on first use)...")
                elif progress_callback is not None:
                    try:
                        progress_callback(0, 1, "loading_model")
                    except TypeError:
                        progress_callback(0, 1)
                self._load_clip_model()
            
            CLIP_AVAILABLE, CLIPProcessor, CLIPModel = _import_clip_modules()
            
            if not self._clip_loaded:
                if not CLIP_AVAILABLE:
                    print("ERROR: CLIP requested but transformers library not installed.")
                    print("Install with: pip install transformers")
                else:
                    print("ERROR: CLIP model failed to load. Check error messages above.")
                print("Falling back to image-based similarity")
                return (displayed_images, None)
            
            # Get text features for the prompt
            text_features = self._get_clip_text_features(text_prompt)
            if text_features is None:
                print("Failed to encode text prompt")
                return (displayed_images, None)
            
            torch, F, transforms, models, ResNet18_Weights, ResNet50_Weights, ResNet101_Weights = _import_torch_modules()
            
            # Set progress range to only images that need processing
            total_steps = len(images_to_process) if images_to_process else 1  # At least 1 to avoid division by zero
            processed_count = 0
            
            # Gather CLIP features for all candidates
            features = {}
            sorted_images = []
            missing = displayed_images[:]  # Default to all images if error occurs
            # Stage 1: Examining images (feature extraction)
            for path in candidates:
                # Check for cancellation before processing each image
                if progress_dialog is not None and progress_dialog.wasCanceled():
                    raise KeyboardInterrupt("User canceled similarity calculation")
                
                # Check if this needs processing (not cached)
                was_cached = self._is_clip_feature_cached(path)
                feat = self._get_clip_image_feature(path)
                # Only update progress if we actually processed it
                if not was_cached:
                    processed_count += 1
                    status_text = "Extracting and caching features... first time may be slow" if processed_count == 1 else "Extracting and caching features..."
                    if progress_tracker is not None:
                        progress_tracker.update_feature_extraction(processed_count, total_steps, status_text)
                    elif progress_callback is not None:
                        try:
                            progress_callback(processed_count, total_steps, "examining_images")
                        except TypeError:
                            progress_callback(float(processed_count) / float(total_steps) if total_steps else 1.0)
                    
                    # Periodically pause background process during foreground extraction (every 5 extractions)
                    if processed_count % 5 == 0:
                        if (self.main_window and 
                            hasattr(self.main_window, 'background_clip_controller') and 
                            self.main_window.background_clip_controller and
                            self.main_window.background_clip_controller.enabled):
                            if self.main_window.background_clip_controller.is_background_active():
                                self.main_window.background_clip_controller.pause_process()
                    
                    # Check for cancellation after progress update
                    if progress_dialog is not None and progress_dialog.wasCanceled():
                        raise KeyboardInterrupt("User canceled similarity calculation")
                if feat is not None:
                    # Ensure feature is on the correct device before storing (for CLIP features)
                    if hasattr(feat, 'device') and hasattr(self, 'device') and feat.device.type != self.device:
                        feat = feat.to(self.device)
                    features[path] = feat
            
            # If all images were cached, update progress to show completion
            if not images_to_process:
                if progress_tracker is not None:
                    progress_tracker.update_feature_extraction(0, 0, "Extracting and caching features...")
                elif progress_callback is not None:
                    try:
                        progress_callback(1, 1, "examining_images")
                    except TypeError:
                        progress_callback(1.0)
            
            # Stage 2: Comparing images (similarity calculation and sorting)
            # Update to comparison stage immediately after feature extraction completes
            if progress_tracker is not None:
                progress_tracker.update_comparison()
            elif progress_callback is not None:
                try:
                    progress_callback(total_steps, total_steps, "comparing_images")
                except TypeError:
                    progress_callback(1.0)
            
            # Check for cancellation before starting comparison
            if progress_dialog is not None and progress_dialog.wasCanceled():
                raise KeyboardInterrupt("User canceled similarity calculation")
            
            # Score and sort using cosine similarity (CLIP features are normalized)
            scored = []
            highest_score_overall = None  # Track highest score even if filtered out
            comparison_count = 0
            total_comparisons = len([p for p in candidates if p in features])
            for path in candidates:
                if path not in features:
                    continue
                
                # Check for cancellation during comparison loop
                if progress_dialog is not None and progress_dialog.wasCanceled():
                    raise KeyboardInterrupt("User canceled similarity calculation")
                
                # Use cosine similarity (dot product since features are normalized)
                similarity = torch.dot(text_features, features[path]).item()
                
                # Increment comparison count immediately after comparison (counts all comparisons, not just found)
                comparison_count += 1
                
                # Track highest score regardless of threshold
                if highest_score_overall is None or similarity > highest_score_overall:
                    highest_score_overall = similarity
                
                # Filter based on threshold if provided
                should_skip = False
                if filter_below_threshold and similarity_threshold is not None:
                    if similarity < similarity_threshold:
                        should_skip = True  # Skip this image - doesn't match threshold
                
                # Update progress during comparison (show incremental progress for all comparisons)
                if progress_tracker is not None and total_comparisons > 0:
                    # Update UI only on 1st (comparison_count == 1) and every 10th displayed number (10, 20, 30...), or last item
                    # comparison_count is 1-indexed, so comparison_count % 10 == 0 matches 10, 20, 30, etc.
                    should_update_ui = (comparison_count == 1 or comparison_count % 10 == 0 or comparison_count == total_comparisons)
                    
                    if should_update_ui:
                        # Update comparison progress (already in comparison stage, just show progress)
                        comparison_progress = float(comparison_count) / float(total_comparisons)
                        comparison_value = int(progress_tracker.comparison_start + 
                                             comparison_progress * (100 - progress_tracker.comparison_start))
                        progress_dialog.setValue(min(comparison_value, 100))
                        progress_dialog.setStatusText(f"Calculating similarities... ({comparison_count}/{total_comparisons})")
                elif progress_callback is not None and total_comparisons > 0:
                    # For callback-based progress, update with comparison progress
                    try:
                        progress_callback(comparison_count, total_comparisons, "comparing_images")
                    except TypeError:
                        progress_callback(float(comparison_count) / float(total_comparisons) if total_comparisons else 1.0)
                
                # Skip images that don't meet threshold (but comparison was already counted above)
                if should_skip:
                    continue
                
                scored.append((similarity, path))
            
            scored.sort(reverse=True, key=lambda tup: tup[0])
            sorted_images = [p for _, p in scored]
            
            # Get highest score for return value
            # Use highest_score_overall if no images passed threshold, otherwise use highest from scored
            if scored:
                highest_score = scored[0][0]
            else:
                highest_score = highest_score_overall  # Show highest score even if below threshold
            
            # Only add missing/unreadable images if NOT filtering by threshold
            # When filtering is enabled, we want ONLY the matching images
            if filter_below_threshold and similarity_threshold is not None:
                missing = []  # Don't add any images that failed threshold
            else:
                # Add missing/unreadable images that are also not in .Trashes/.Trash or Photos Library
                missing = [p for p in displayed_images if p not in sorted_images and not _is_inside_macos_trash(p) and not is_inside_photos_library_resources_or_scopes(p)]
            
            if progress_tracker is not None:
                progress_tracker.complete()
            elif progress_callback is not None:
                try:
                    progress_callback(total_steps, total_steps)
                except TypeError:
                    progress_callback(1.0)
            
            return (sorted_images + missing, highest_score)
            
        finally:
            # Flush cache to disk at end of operation (or on cancel/error)
            # Use async flush to avoid blocking main thread during recursive searches
            # which can have thousands of cached features
            if self.feature_cache:
                self.feature_cache.flush_caches(async_flush=True)
            
            # Resume background CLIP extraction after foreground extraction completes
            if background_was_paused:
                if (self.main_window and 
                    hasattr(self.main_window, 'background_clip_controller') and 
                    self.main_window.background_clip_controller and
                    self.main_window.background_clip_controller.enabled):
                    # Resume with current directory prioritized
                    current_dir = getattr(self.main_window, 'current_directory', None)
                    self.main_window.background_clip_controller.resume_process(priority_directory=current_dir)

    def reorder_by_similarity(self, displayed_images, ref_image_path, progress_callback=None, text_prompt=None, progress_dialog=None):
        """
        Args:
            displayed_images: List[str] file paths of displayed images
            ref_image_path: File path to the "active" (reference) image, or List[str] of reference image paths.
                           If a list is provided, feature vectors will be averaged to create an aggregate reference.
                           Can be None if text_prompt is provided.
            progress_callback: function(float) or function(int, int), optional.
                               Called as progress_callback(completed, total)
                               (value is in 0..1 or 0..100 or (completed, total)).
            text_prompt: Optional text prompt for CLIP-based search. If provided, uses CLIP instead of CNN.
            progress_dialog: Optional ProgressDialogWithStatus instance for staged progress tracking
        Returns:
            List[str]: reordered list, closest to ref_image_path (or aggregate) or text_prompt first
        """
        # If text prompt is provided, use CLIP-based search
        if text_prompt:
            return self.reorder_by_text_prompt(displayed_images, text_prompt, progress_callback)
        
        # Otherwise, use image-based similarity (original behavior)
        # Normalize ref_image_path to always be a list for consistent handling
        if isinstance(ref_image_path, str):
            ref_image_paths = [ref_image_path]
        else:
            ref_image_paths = list(ref_image_path)
        
        if not ref_image_paths:
            print("No reference images provided.")
            if progress_callback is not None:
                progress_callback(1.0)
            return displayed_images

        # Safety: filter for image files that exist and valid extension and NOT in .Trashes/.Trash or Photos Library
        # Use set for faster extension checking
        extensions_set = set(self.extensions)
        candidates = [
            p for p in displayed_images
            if isinstance(p, str)
            and os.path.exists(p)
            and os.path.splitext(p.lower())[1] in extensions_set
            and not _is_inside_macos_trash(p)
            and not is_inside_photos_library_resources_or_scopes(p)
        ]
        candidates_set = set(candidates)

        # Clean up feature cache for images no longer present
        self._evict_vanished_features(candidates_set)

        # Filter reference paths to only those that are valid and in candidates
        # Normalize reference paths to match how candidates are normalized (using realpath)
        normalized_ref_paths = []
        for p in ref_image_paths:
            if isinstance(p, str) and os.path.exists(p):
                try:
                    normalized = os.path.realpath(os.path.abspath(os.path.expanduser(p)))
                    normalized_ref_paths.append(normalized)
                except (OSError, ValueError):
                    normalized = os.path.abspath(os.path.expanduser(p))
                    normalized_ref_paths.append(normalized)
        
        # Also normalize candidates for consistent comparison
        normalized_candidates = []
        normalized_candidates_set = set()
        for p in candidates:
            if isinstance(p, str) and os.path.exists(p):
                try:
                    normalized = os.path.realpath(os.path.abspath(os.path.expanduser(p)))
                    if normalized not in normalized_candidates_set:
                        normalized_candidates.append(normalized)
                        normalized_candidates_set.add(normalized)
                except (OSError, ValueError):
                    normalized = os.path.abspath(os.path.expanduser(p))
                    if normalized not in normalized_candidates_set:
                        normalized_candidates.append(normalized)
                        normalized_candidates_set.add(normalized)
            else:
                # Keep non-existent paths as-is
                if p not in normalized_candidates_set:
                    normalized_candidates.append(p)
                    normalized_candidates_set.add(p)
        
        # Filter reference paths to only those that are valid and in normalized candidates
        # Use set for faster extension checking
        extensions_set = set(self.extensions)
        valid_ref_paths = [
            p for p in normalized_ref_paths
            if isinstance(p, str)
            and os.path.exists(p)
            and os.path.splitext(p.lower())[1] in extensions_set
            and not _is_inside_macos_trash(p)
            and not is_inside_photos_library_resources_or_scopes(p)
            and p in normalized_candidates_set
        ]
        
        if not valid_ref_paths:
            # Provide detailed debugging information
            print(f"No valid reference images found in displayed_images.")
            print(f"Reference paths provided: {ref_image_paths}")
            print(f"Normalized reference paths: {normalized_ref_paths}")
            print(f"Total candidates: {len(candidates)}, Normalized candidates: {len(normalized_candidates_set)}")
            if normalized_ref_paths:
                ref_path = normalized_ref_paths[0]
                print(f"First reference path: {ref_path}")
                print(f"  - Exists: {os.path.exists(ref_path)}")
                extensions_set = set(self.extensions)
                print(f"  - Extension match: {os.path.splitext(ref_path.lower())[1] in extensions_set}")
                print(f"  - In trash: {_is_inside_macos_trash(ref_path)}")
                print(f"  - In Photos Library: {is_inside_photos_library_resources_or_scopes(ref_path)}")
                print(f"  - In candidates_set: {ref_path in normalized_candidates_set}")
                if ref_path not in normalized_candidates_set:
                    # Try to find similar paths
                    similar = [c for c in normalized_candidates_set if os.path.basename(c) == os.path.basename(ref_path)]
                    if similar:
                        print(f"  - Found similar paths with same basename: {similar[:3]}")
            if progress_callback is not None:
                progress_callback(1.0)
            return displayed_images
        
        # Use normalized candidates for the rest of the function
        candidates = normalized_candidates
        candidates_set = normalized_candidates_set

        total = len(candidates)
        if total == 0:
            if progress_callback is not None:
                try:
                    progress_callback(1.0)
                except Exception as e:
                    print(f"Error in progress callback: {e}")
                    import traceback
                    traceback.print_exc()
                    pass
            return displayed_images

        # Only cache the sorted results if displayed_images candidates and ref_image_path did not change;
        # Otherwise, if only the reference image changes, reuse feature vectors and recompute only similarity/sorting.

        # Create a cache key from the sorted tuple of reference paths
        ref_paths_key = tuple(sorted(valid_ref_paths))
        
        # Check if both the set and order of candidates and reference are unchanged
        cache_valid = (
            self._last_candidates_set is not None
            and self._last_sorted is not None
            and self._last_candidates_set == candidates_set
            and getattr(self, "_last_sorted_ref_paths", None) == ref_paths_key
        )
        if cache_valid:
            # Already sorted for this ref; "missing" may show up (unreadable etc)
            missing = [p for p in displayed_images if p not in self._last_sorted and not _is_inside_macos_trash(p) and not is_inside_photos_library_resources_or_scopes(p)]
            if progress_callback is not None:
                try:
                    progress_callback(1.0)
                except Exception as e:
                    print(f"Error in progress callback: {e}")
                    import traceback
                    traceback.print_exc()
                    pass
            return self._last_sorted + missing

        # Count cache misses before starting to set accurate progress range
        # Ensure cache is loaded for accurate checking
        self._ensure_feature_cache_loaded()
        
        # Count images that need processing (not cached)
        images_to_process = []
        for ref_path in valid_ref_paths:
            if not self._is_feature_cached(ref_path):
                images_to_process.append(ref_path)
        
        for path in candidates:
            if path not in valid_ref_paths:
                if not self._is_feature_cached(path):
                    images_to_process.append(path)
        
        # Create staged progress tracker if we have a progress_dialog
        progress_tracker = None
        if progress_dialog is not None:
            progress_tracker = StagedProgressTracker(progress_dialog, len(images_to_process))
        
        # Notify about model loading stage (if needed)
        if not self._model_loaded:
            if progress_tracker is not None:
                progress_tracker.update_model_loading("Loading CNN model...")
            elif progress_callback is not None:
                try:
                    progress_callback(0, 1, "loading_model")
                except TypeError:
                    progress_callback(0, 1)
        
        # Set progress range to only images that need processing
        total_steps = len(images_to_process) if images_to_process else 1  # At least 1 to avoid division by zero
        processed_count = 0

        # Step 1: Gather features for reference images and aggregate them
        ref_features = []
        for ref_path in valid_ref_paths:
            # Check for cancellation before processing each image
            if progress_dialog is not None and progress_dialog.wasCanceled():
                raise KeyboardInterrupt("User canceled similarity calculation")
            
            # Check if this needs processing (not cached)
            was_cached = self._is_feature_cached(ref_path)
            ref_feat = self._get_feature(ref_path)
            # Only update progress if we actually processed it
            if not was_cached:
                processed_count += 1
                if progress_tracker is not None:
                    progress_tracker.update_feature_extraction(processed_count, total_steps, "Extracting and caching features...")
                elif progress_callback is not None:
                    try:
                        progress_callback(processed_count, total_steps, "examining_images")
                    except TypeError:
                        progress_callback(float(processed_count) / float(total_steps) if total_steps else 1.0)
                # Check for cancellation after progress update
                if progress_dialog is not None and progress_dialog.wasCanceled():
                    raise KeyboardInterrupt("User canceled similarity calculation")
            if ref_feat is not None:
                ref_features.append(ref_feat)
        
        # If all images were cached, update progress to show completion
        if not images_to_process:
            if progress_tracker is not None:
                progress_tracker.update_feature_extraction(0, 0, "Extracting and caching features...")
            elif progress_callback is not None:
                try:
                    progress_callback(1, 1, "examining_images")
                except TypeError:
                    progress_callback(1.0)
        
        if not ref_features:
            print("Could not extract features for any reference images.")
            if progress_callback is not None:
                try:
                    progress_callback(1.0)
                except Exception:
                    pass
            return displayed_images

        # Aggregate reference features by averaging
        torch, F, transforms, models, ResNet18_Weights, ResNet50_Weights, ResNet101_Weights = _import_torch_modules()
        
        # Ensure all reference features are on the same device
        ref_features_on_device = []
        for feat in ref_features:
            if feat is not None:
                if feat.device.type != self.device:
                    feat = feat.to(self.device)
                ref_features_on_device.append(feat)
        
        if len(ref_features_on_device) == 0:
            print("Could not extract features for any reference images.")
            if progress_callback is not None:
                try:
                    progress_callback(1.0)
                except Exception:
                    pass
            return displayed_images
        
        if len(ref_features_on_device) == 1:
            aggregate_ref_feat = ref_features_on_device[0]
        else:
            # Stack features and compute mean
            ref_features_tensor = torch.stack(ref_features_on_device)
            aggregate_ref_feat = torch.mean(ref_features_tensor, dim=0)

        # Gather features for all remaining candidates (excluding reference images already processed)
        features = {}
        # Store reference features in features dict (already on correct device from ref_features_on_device)
        for i, ref_path in enumerate(valid_ref_paths):
            if i < len(ref_features_on_device):
                features[ref_path] = ref_features_on_device[i]
        
        sorted_images = displayed_images[:]  # Default to original order if error occurs
        missing = []
        try:
            for path in candidates:
                if path in valid_ref_paths:
                    continue  # Already processed above
                
                # Check for cancellation before processing each image
                if progress_dialog is not None and progress_dialog.wasCanceled():
                    raise KeyboardInterrupt("User canceled similarity calculation")
                
                # Check if this needs processing (not cached)
                was_cached = self._is_feature_cached(path)
                feat = self._get_feature(path)
                # Only update progress if we actually processed it
                if not was_cached:
                    processed_count += 1
                    if progress_tracker is not None:
                        progress_tracker.update_feature_extraction(processed_count, total_steps, "Extracting and caching features...")
                    elif progress_callback is not None:
                        try:
                            progress_callback(processed_count, total_steps, "examining_images")
                        except TypeError:
                            progress_callback(float(processed_count) / float(total_steps) if total_steps else 1.0)
                    # Check for cancellation after progress update
                    if progress_dialog is not None and progress_dialog.wasCanceled():
                        raise KeyboardInterrupt("User canceled similarity calculation")
                if feat is not None:
                    # Ensure feature is on the correct device before storing
                    if feat.device.type != self.device:
                        feat = feat.to(self.device)
                    features[path] = feat

            # Step 2: Score and sort using the selected similarity metric
            # Update to comparison stage immediately after feature extraction completes
            if progress_tracker is not None:
                progress_tracker.update_comparison()
            elif progress_callback is not None:
                try:
                    progress_callback(total_steps, total_steps, "comparing_images")
                except TypeError:
                    progress_callback(1.0)
            
            # Check for cancellation before starting comparison
            if progress_dialog is not None and progress_dialog.wasCanceled():
                raise KeyboardInterrupt("User canceled similarity calculation")
            
            scored = []
            comparison_count = 0
            total_comparisons = len([p for p in candidates if p in features])
            for path in candidates:
                if path not in features:
                    continue
                
                # Check for cancellation during comparison loop
                if progress_dialog is not None and progress_dialog.wasCanceled():
                    raise KeyboardInterrupt("User canceled similarity calculation")
                
                if path in valid_ref_paths:
                    # Reference images always have maximum similarity
                    similarity = 1.0
                else:
                    # Compute similarity using the selected metric against aggregate reference
                    try:
                        similarity = self._compute_similarity(aggregate_ref_feat, features[path])
                    except RuntimeError as e:
                        if "device" in str(e).lower() or "Expected all tensors to be on the same device" in str(e):
                            # Device mismatch error - show user-friendly message and cancel operation
                            error_msg = (
                                "Device mismatch error during similarity calculation.\n\n"
                                "This can occur when tensors are on different devices (CPU vs GPU).\n"
                                "The operation has been cancelled.\n\n"
                                f"Error details: {str(e)}"
                            )
                            print(f"Device mismatch error: {e}")
                            # Try to show error dialog if possible
                            try:
                                QtWidgets, QtCore = _import_qt_modules()
                                if QtWidgets and QtWidgets.get('QMessageBox'):
                                    QMessageBox = QtWidgets['QMessageBox']
                                    msg_box = QMessageBox()
                                    msg_box.setIcon(QMessageBox.Icon.Critical)
                                    msg_box.setWindowTitle("Similarity Calculation Error")
                                    msg_box.setText(error_msg)
                                    msg_box.exec()
                            except Exception:
                                # If we can't show dialog, at least print the error
                                print(error_msg)
                            # Return original order
                            return displayed_images
                        else:
                            # Re-raise other RuntimeErrors
                            raise
                scored.append((similarity, path))
                
                # Update progress during comparison (show incremental progress)
                comparison_count += 1
                if progress_tracker is not None and total_comparisons > 0:
                    # Only update UI when the number remaining is a multiple of 10 or it's the initial number
                    comparisons_left = total_comparisons - comparison_count + 1
                    should_update_ui = (
                        comparisons_left % 10 == 0
                        or comparisons_left == total_comparisons
                        or comparisons_left == 1  # always update on the very last image
                    )

                    if should_update_ui:
                        comparison_progress = float(comparison_count) / float(total_comparisons)
                        comparison_value = int(progress_tracker.comparison_start +
                                              comparison_progress * (100 - progress_tracker.comparison_start))
                        progress_dialog.setValue(min(comparison_value, 100))
                        progress_dialog.setStatusText(f"Calculating similarities... ({comparison_count}/{total_comparisons})")
                elif progress_callback is not None and total_comparisons > 0:
                    try:
                        progress_callback(comparison_count, total_comparisons, "comparing_images")
                    except TypeError:
                        progress_callback(float(comparison_count) / float(total_comparisons) if total_comparisons else 1.0)

            scored.sort(reverse=True, key=lambda tup: tup[0])
            sorted_images = [p for _, p in scored]
            # Add missing/unreadable images unmodified at the end, ONLY if not in .Trashes/.Trash or Photos Library
            missing = [p for p in displayed_images if p not in sorted_images and not _is_inside_macos_trash(p) and not is_inside_photos_library_resources_or_scopes(p)]
            
            # Store cache: we store only for the last candidates and reference used to sort
            self._last_candidates_set = set(candidates)
            self._last_sorted = sorted_images
            self._last_sorted_ref_paths = ref_paths_key
        finally:
            # Flush cache to disk at end of operation (or on cancel/error)
            # Use async flush to avoid blocking main thread during recursive searches
            # which can have thousands of cached features
            if self.feature_cache:
                self.feature_cache.flush_caches(async_flush=True)
        
        if progress_tracker is not None:
            progress_tracker.complete()
        elif progress_callback is not None:
            try:
                progress_callback(total_steps, total_steps)
            except TypeError:
                progress_callback(1.0)
        
        return sorted_images + missing

def main():
    import glob

    image_dir = os.path.expanduser('~/tmp/barney')
    # Accept .jpg, .jpeg, .png, .webp
    extensions = ('*.jpg', '*.jpeg', '*.png', '*.webp')
    files = []
    for ext in extensions:
        files.extend(glob.glob(os.path.join(image_dir, ext)))
    files = sorted(files)
    if not files:
        print("No images found in", image_dir)
        return

    def progress_cb(current, total=None):
        if total is not None:
            pct = int(float(current) / float(total) * 100) if total else 100
            print(f"Progress: {pct}% ({current}/{total})")
        else:
            # fallback for float progress
            print(f"Progress: {int(current * 100)}%")

    sorter = CNNImageSimilaritySorter()
    reference_image = files[0]  # Pick the first image as "active"
    print("Reference image:", reference_image)
    sorted_list = sorter.reorder_by_similarity(files, reference_image, progress_callback=progress_cb)
    print("Reordered:")
    for i, f in enumerate(sorted_list):
        marker = "(REF)" if f == reference_image else ""
        print(f"{i:3d}: {os.path.basename(f)} {marker}")

if __name__ == "__main__":
    main()
