#!/usr/bin/env python3
"""
External Editor Integration with Timestamp Preservation
Handles launching configured image editor applications to edit images while preserving original file dates/times

Enhanced Features:
- Comprehensive cache clearing (both memory and disk) for edited images
- Improved thumbnail refresh logic that handles all view modes
- Adjacent thumbnail refresh for smooth navigation
- Multiple editing session tracking
- Robust error handling with fallback refresh methods
- Prevention of rapid successive refreshes during editing
- Support for both current and future image views
- Configurable editor selection via Settings > Apps
"""

# Standard library imports
import os
import subprocess
import threading
import time
from typing import Optional
import traceback
import psutil
from PySide6.QtCore import QMutexLocker
from macos_process import open_document_with_app
from utils import get_main_window, show_styled_critical
from config import get_config


class TimestampPreservingEditor:
    """
    Manages external editing with timestamp preservation
    """
    
    def __init__(self, check_interval: float = 2.0):
        """
        Initialize the editor manager
        
        Args:
            check_interval: How often to check and restore timestamps (seconds)
        """
        self.check_interval = check_interval
        self.monitoring = False
        self.monitor_thread = None
        self.original_mtime = None
        self.original_atime = None
        self.original_usercomment = None  # EXIF UserComment to restore if editor strips it
        self.file_path = None
        self.editor_pid = None
        self.refresh_callback = None
        self._timestamp_lock = threading.Lock()
    
    def _get_editor_app_name(self) -> str:
        """Get the configured image editor application name"""
        config = get_config()
        settings = config.load_settings()
        return settings.get('image_editor_app', 'Preview')
        
    def edit_file_in_editor(self, file_path: str, refresh_callback=None) -> bool:
        """
        Edit a file in the configured image editor while preserving its original timestamps
        
        Args:
            file_path: Path to the file to edit
            refresh_callback: Optional callback function to refresh the UI when file changes
            
        Returns:
            bool: True if successful, False otherwise
        """
        if not self._validate_file(file_path):
            return False
            
        # Store the refresh callback
        self.refresh_callback = refresh_callback
        
        # Get the configured editor app name
        editor_app = self._get_editor_app_name()
            
        try:
            # Save original timestamps
            self._save_original_timestamps(file_path)
            
            # Launch the editor and get its PID
            success, pid = self._launch_editor(editor_app, file_path)
            
            if success:
                self.editor_pid = pid
                # Start monitoring in background - will continue until editor closes
                # Only start monitoring if we have a valid PID
                if pid is not None:
                    self._start_monitoring()
                return True
            else:
                # Show QMessageBox error about not installed/not launchable app
                self._show_editor_not_installed_error(editor_app)
                return False
                
        except Exception:
            # Show QMessageBox error about not installed/not launchable app
            self._show_editor_not_installed_error(editor_app)
            return False

    def _show_editor_not_installed_error(self, editor_app: str):
        try:
            main_win = get_main_window()
            if main_win is not None:
                show_styled_critical(
                    main_win,
                    f"{editor_app} Not Installed",
                    f"{editor_app} could not be launched. It is likely not installed on this system.<br>"
                    "Please install it or select a different editor in Settings > Apps.",
                )
            else:
                print(f"ERROR: {editor_app} is not installed or could not be launched.")
        except Exception:
            print(f"ERROR: {editor_app} is not installed or could not be launched.")

    def _validate_file(self, file_path: str) -> bool:
        """
        Validate that the file exists and can be accessed
        
        Args:
            file_path: Path to validate
            
        Returns:
            bool: True if file is valid, False otherwise
        """

        if (
            not os.path.exists(file_path) or
            not os.path.isfile(file_path) or
            not os.access(file_path, os.R_OK)
        ):
            return False
            
        # Store the file path for monitoring
        self.file_path = file_path
        return True
    
    def _save_original_timestamps(self, file_path: str) -> None:
        """
        Save the original access and modification times, and EXIF UserComment if present.

        Args:
            file_path: Path to the file
        """
        stat_info = os.stat(file_path)
        self.original_atime = stat_info.st_atime
        self.original_mtime = stat_info.st_mtime
        try:
            from exif.exif_utils import get_usercomment_from_path
            self.original_usercomment = get_usercomment_from_path(file_path)
        except Exception:
            self.original_usercomment = None

    def _check_editor_installed(self, editor_app: str) -> bool:
        """
        Check if the specified editor application is installed on the system
        
        Args:
            editor_app: Name of the application (e.g., "Preview")
        
        Returns:
            bool: True if installed, False otherwise
        """
        # Check common installation locations
        app_paths = [
            f'/Applications/{editor_app}.app',
            f'/System/Applications/{editor_app}.app',  # System apps (e.g., Preview)
            os.path.expanduser(f'~/Applications/{editor_app}.app'),
        ]
        
        for app_path in app_paths:
            if os.path.exists(app_path) and os.path.isdir(app_path):
                return True
        
        return False
    
    def _launch_editor(self, editor_app: str, file_path: str) -> tuple[bool, Optional[int]]:
        """
        Launch the specified editor application with the specified file
        
        Args:
            editor_app: Name of the application (e.g., "Preview")
            file_path: Path to the file to open
            
        Returns:
            tuple: (success: bool, pid: Optional[int]) - True if launch was successful, PID if found
        """
        try:
            # Check if editor is installed
            if not self._check_editor_installed(editor_app):
                return False, None
            
            # Check if editor is already running before launching
            existing_pid = self._find_editor_pid(editor_app)
            
            # Use 'open' command to launch the editor with the file
            # The -a flag specifies the application
            result = open_document_with_app(editor_app, os.path.abspath(file_path), timeout=10)
            
            # Check if open command failed
            if result.returncode != 0:
                # If open failed and we didn't find an existing process, it's a real failure
                if existing_pid is None:
                    return False, None
                # If open failed but process exists, use existing PID
                return True, existing_pid
            
            # Give the application time to start - try multiple times with increasing delays
            # macOS apps can take a moment to fully launch
            for attempt in range(5):
                time.sleep(0.5 + attempt * 0.5)  # 0.5s, 1.0s, 1.5s, 2.0s, 2.5s
                pid = self._find_editor_pid(editor_app)
                if pid is not None:
                    return True, pid
            
            # If we still can't find it but open succeeded, check if it was already running
            # The open command succeeded, so consider it successful even if we can't find PID
            if existing_pid is not None:
                return True, existing_pid
            
            # If open succeeded but we can't find the process, still consider it successful
            # The file should have opened even if process detection failed
            # Return None for PID but True for success
            return True, None
                
        except subprocess.TimeoutExpired:
            return False, None
        except subprocess.SubprocessError:
            return False, None
        except Exception:
            return False, None
    
    def _find_editor_pid(self, editor_app: str) -> Optional[int]:
        """
        Find the process ID of the specified editor application
        
        Args:
            editor_app: Name of the application (e.g., "Preview")
        
        Returns:
            Optional[int]: Process ID if found, None otherwise
        """
        try:
            # Use psutil to find the editor process
            # On macOS, check process name, command line, and executable path
            # Normalize app name for matching (lowercase, handle spaces)
            app_name_lower = editor_app.lower()
            app_name_no_spaces = app_name_lower.replace(' ', '')
            app_name_with_app = f"{app_name_lower}.app"
            
            found_pids = []
            
            for proc in psutil.process_iter():
                try:
                    # Get process information using Process object methods for more reliable data
                    name = proc.name().lower()
                    try:
                        cmdline_list = proc.cmdline()
                        cmdline = ' '.join(cmdline_list).lower() if cmdline_list else ''
                    except (psutil.AccessDenied, psutil.ZombieProcess):
                        cmdline = ''
                    
                    try:
                        exe = proc.exe().lower()
                    except (psutil.AccessDenied, psutil.ZombieProcess, psutil.NoSuchProcess):
                        exe = ''
                    
                    # Check for editor app in various forms
                    # Prefer exact matches
                    if (app_name_lower in name or app_name_lower in cmdline or app_name_lower in exe or
                        app_name_no_spaces in name or app_name_no_spaces in cmdline or app_name_no_spaces in exe or
                        app_name_with_app in exe or app_name_with_app in cmdline):
                        found_pids.append((proc.pid, True))  # True = exact match
                    
                except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                    # Process may have terminated or we don't have access
                    continue
            
            # Return the first match
            if found_pids:
                return found_pids[0][0]
            
            return None
            
        except Exception:
            return None
    
    def _is_editor_running(self) -> bool:
        """
        Check if the editor is still running
        
        Returns:
            bool: True if editor is running, False otherwise
        """
        if self.editor_pid is None:
            return False
        
        # Get the configured editor app name
        editor_app = self._get_editor_app_name()
            
        try:
            # Check if the specific process is still running using psutil
            if psutil.pid_exists(self.editor_pid):
                try:
                    proc = psutil.Process(self.editor_pid)
                    # Verify it's actually the editor
                    name = proc.name().lower()
                    try:
                        cmdline = ' '.join(proc.cmdline()).lower()
                    except (psutil.AccessDenied, psutil.ZombieProcess):
                        cmdline = ''
                    try:
                        exe = proc.exe().lower()
                    except (psutil.AccessDenied, psutil.ZombieProcess, psutil.NoSuchProcess):
                        exe = ''
                    
                    editor_app_lower = editor_app.lower()
                    editor_app_no_spaces = editor_app_lower.replace(' ', '')
                    
                    if (editor_app_lower in name or editor_app_lower in cmdline or editor_app_lower in exe or
                        editor_app_no_spaces in name or editor_app_no_spaces in cmdline or editor_app_no_spaces in exe):
                        return True
                except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                    pass
            
            # If specific PID not found, check if any editor process is running
            # This handles cases where the process might have restarted with a new PID
            new_pid = self._find_editor_pid(editor_app)
            if new_pid is not None:
                if new_pid != self.editor_pid:
                    self.editor_pid = new_pid
                return True
            
            return False
            
        except Exception:
            return False
    
    def _start_monitoring(self) -> None:
        """
        Start the timestamp monitoring thread
        """
        if self.monitor_thread and self.monitor_thread.is_alive():
            return
            
        self.monitoring = True
        self.monitor_thread = threading.Thread(
            target=self._monitor_timestamps,
            daemon=True
        )
        self.monitor_thread.start()
    
    
    
    def _monitor_timestamps(self) -> None:
        """
        Monitor and restore timestamps while editing is in progress
        This runs in a background thread and continues until the external editor closes
        """
        check_count = 0
        
        while self.monitoring and self.file_path:
            try:
                time.sleep(self.check_interval)
                check_count += 1
                
                if not self.monitoring:
                    break
                
                # Check if editor is still running
                if not self._is_editor_running():
                    break
                    
                # Check if file still exists
                if not os.path.exists(self.file_path):
                    continue
                
                # Get current timestamps
                stat_info = os.stat(self.file_path)
                current_mtime = stat_info.st_mtime
                
                # If modification time has changed, restore it and trigger refresh
                # Skip restore if the app intentionally changed mtime (e.g. drag/drop date update)
                with self._timestamp_lock:
                    orig_mtime = self.original_mtime
                if abs(current_mtime - orig_mtime) > 1.0:  # Allow 1 second tolerance
                    self._restore_timestamps()
                    
                    # Trigger UI refresh if callback is provided
                    if self.refresh_callback:
                        try:
                            # Can't use QTimer.singleShot on this thread; emit to main thread via signal (see chat_history_0)
                            main_window = get_main_window()
                            if main_window:
                                main_window.cache_manager.clear_cache_for_file(self.file_path)
                                if hasattr(main_window, 'RefreshEmitter'):
                                    main_window.RefreshEmitter.refresh.connect(self.refresh_callback)
                                    main_window.RefreshEmitter.refresh.emit(self.file_path)
                                    main_window.RefreshEmitter.refresh.disconnect()
                        except Exception as e:
                            print(f"Error triggering refresh callback: {e}")
                            traceback.print_exc()
                            pass
                    else:
                        pass
                    
                    # Update the original mtime to the restored value to avoid repeated triggers
                    # We need to get the actual restored timestamp
                    try:
                        stat_info = os.stat(self.file_path)
                        self.original_mtime = stat_info.st_mtime
                    except Exception as e:
                        pass
                    
                    # Add a small delay to prevent rapid successive refreshes
                    # This helps when the editor saves multiple times quickly
                    time.sleep(0.5)
                    
            except Exception as e:
                continue
        
        # Final timestamp restoration when monitoring ends
        if self.file_path and os.path.exists(self.file_path):
            self._restore_timestamps()
        else:
            pass
        
        # Clean up
        self.monitoring = False
        self.editor_pid = None
        self.refresh_callback = None
        self.original_usercomment = None

        # Clear session tracking
        if self.file_path:
            clear_editing_session(self.file_path)
    
    def _restore_timestamps(self) -> None:
        """
        Restore the original timestamps and EXIF UserComment (if one existed) to the file.
        """
        if not self.file_path or not os.path.exists(self.file_path):
            return

        if self.original_atime is None or self.original_mtime is None:
            return

        try:
            # Restore EXIF UserComment first - writing modifies mtime, so utime must come after
            if self.original_usercomment:
                try:
                    from exif.exif_utils import restore_usercomment_to_file
                    restore_usercomment_to_file(self.file_path, self.original_usercomment)
                except Exception as e:
                    print(f"DEBUG _restore_timestamps: usercomment restore failed: {e}")
            # Restore timestamps after EXIF write so mtime is set correctly
            os.utime(self.file_path, (self.original_atime, self.original_mtime))
            # Invalidate the thumbnail for self.file_path by removing its pixmap and any related cache
            try:
                main_window = get_main_window()
                cache_manager = getattr(main_window, "cache_manager", None)
                if cache_manager is not None:
                    cache_manager.clear_cache_for_file(self.file_path)
                # Find and clear the pixmap for this file in the thumbnail grid
                # CRITICAL: Also mark as loading so it gets reloaded
                canvas = main_window.thumbnail_container.canvas
                with QMutexLocker(canvas.mutex):
                    for thumb in canvas.thumbnails:
                        if getattr(thumb, "image_path", None) == self.file_path:
                            thumb.pixmap = None
                            thumb.is_loading = True
                            break
                # Trigger thumbnail loading on main thread - must not call from background
                # thread (causes QTimer.singleShot which triggers Qt warning + print deadlock)
                if hasattr(main_window, 'RefreshEmitter') and hasattr(main_window.RefreshEmitter, 'load_thumbnails_requested'):
                    main_window.RefreshEmitter.load_thumbnails_requested.emit()
            except Exception as e:
                print(f"Error invalidating thumbnail for {self.file_path}: {e}")
                traceback.print_exc()
        except Exception as e:
            print(f"Error restoring timestamps: {e}")
            traceback.print_exc()
            pass

    def _notify_mtime_changed_by_app(self, file_path: str, new_mtime: float) -> None:
        """
        Called when the app intentionally changes a file's mtime (e.g. drag/drop date update).
        Update our stored original so we don't incorrectly restore it.
        """
        if not self.monitoring or not self.file_path or self.file_path != file_path:
            return
        with self._timestamp_lock:
            self.original_mtime = new_mtime
            self.original_atime = new_mtime

# Global instance for easy access
_editor_instance = TimestampPreservingEditor()


def notify_mtime_changed_by_app(file_path: str, new_mtime: float) -> None:
    """
    Notify the external editor that the app intentionally changed a file's mtime.
    When the monitored file's mtime is changed by drag/drop or other in-app operations,
    we must update our stored original so we don't incorrectly restore it.
    """
    _editor_instance._notify_mtime_changed_by_app(file_path, new_mtime)

# Track multiple editing sessions
_active_editing_sessions = {}

def edit_with_editor(file_path: str, refresh_callback=None) -> bool:
    """
    Convenience function to edit a file in the configured editor with timestamp preservation
    
    Args:
        file_path: Path to the file to edit
        refresh_callback: Optional callback function to refresh the UI when file changes
        
    Returns:
        bool: True if successful, False otherwise
    """
    # Track this editing session
    _active_editing_sessions[file_path] = {
        'start_time': time.time(),
        'refresh_callback': refresh_callback
    }
    
    success = _editor_instance.edit_file_in_editor(file_path, refresh_callback)
    
    if not success:
        # Remove from tracking if failed
        _active_editing_sessions.pop(file_path, None)
    
    return success

def clear_editing_session(file_path: str) -> None:
    """
    Clear tracking for a specific editing session
    
    Args:
        file_path: Path to the file being edited
    """
    _active_editing_sessions.pop(file_path, None)


def edit_current_image_with_editor(image_browser_instance) -> bool:
    """
    Edit the currently selected image in the image browser with the configured editor
    
    Args:
        image_browser_instance: Instance of the main image browser
        
    Returns:
        bool: True if successful, False otherwise
    """
    # Do nothing when more than 1 file is selected (guard for Cmd+E when menu state lags)
    if getattr(image_browser_instance, 'multi_select_mode', False):
        return False
    # Get the currently displayed images using the new method
    displayed_images = image_browser_instance.get_displayed_images()
    if not displayed_images:
        return False
    
    # Determine the current view mode to decide which image to edit
    current_view_mode = getattr(image_browser_instance, 'current_view_mode', 'thumbnail')
    
    # In browse mode, use current_image_path if available
    if (current_view_mode == 'browse' and 
        hasattr(image_browser_instance, 'current_image_path') and 
        image_browser_instance.current_image_path):
        
        current_image_path = image_browser_instance.current_image_path
        
        # Create a refresh callback that updates the UI for this specific image
        def refresh_callback(file_path):
            # print(f"external_editor.py: refresh_callback: calling load_directory - instance 1")
            # image_browser_instance.main_window.load_directory(image_browser_instance.current_directory, external_load=True)
            refresh_image_in_browser(image_browser_instance, file_path)
        return edit_with_editor(str(current_image_path), refresh_callback)
    
    # In thumbnail mode, use the highlighted image (highlight_index)
    # This ensures we edit the currently highlighted image, not the last browse image
    selected_index = None
    if hasattr(image_browser_instance, 'highlight_index') and image_browser_instance.highlight_index >= 0:
        selected_index = image_browser_instance.highlight_index
    
    if selected_index is None or selected_index < 0:
        return False
        
    try:
        # Get the currently selected image path from displayed images
        if 0 <= selected_index < len(displayed_images):
            current_image_path = displayed_images[selected_index]
        else:
            return False
        
        # Create a refresh callback that updates the UI for this specific image
        def refresh_callback(file_path):
            refresh_image_in_browser(image_browser_instance, file_path)
        
        return edit_with_editor(str(current_image_path), refresh_callback)
        
    except (IndexError, AttributeError):
        return False

def refresh_image_in_browser(image_browser_instance, file_path: str) -> None:
    """
    Refresh the display of a specific image in the browser
    
    Args:
        image_browser_instance: Instance of the main image browser
        file_path: Path to the file to refresh
    """
    try:
        # Get the currently displayed images using the new method
        displayed_images = image_browser_instance.get_displayed_images()
        if not displayed_images:
            return
            
        # Find the image in the displayed images list
        if file_path in displayed_images:
            display_index = displayed_images.index(file_path)
        else:
            # Image not in current view (filtered out)
            return
        
        # Clear all cache for this image (both memory and disk) to force reload
        if image_browser_instance.cache_manager:
            image_browser_instance.cache_manager.clear_cache_for_file(file_path)
        
        # Check current view mode
        current_view_mode = getattr(image_browser_instance, 'current_view_mode', 'unknown')
        
        # Refresh browse display if this image is currently displayed
        # Check if this is the currently highlighted image
        if (current_view_mode == 'browse' and 
            hasattr(image_browser_instance, 'highlight_index') and 
            image_browser_instance.highlight_index >= 0):
            # Get actual image index from highlight_index
            if hasattr(image_browser_instance, 'image_indices') and image_browser_instance.image_indices:
                try:
                    actual_index = image_browser_instance.image_indices[image_browser_instance.highlight_index]
                    if actual_index == display_index:
                        # Reload the browse image (cache already cleared above)
                        if hasattr(image_browser_instance, 'show_image'):
                            image_browser_instance.show_image(file_path, display_index)
                        elif hasattr(image_browser_instance, 'update_image_display'):
                            image_browser_instance.update_image_display()
                except (IndexError, ValueError):
                    pass
            else:
                # Fallback to direct mapping
                if image_browser_instance.highlight_index == display_index:
                    # Reload the browse image (cache already cleared above)
                    if hasattr(image_browser_instance, 'show_image'):
                        image_browser_instance.show_image(file_path, display_index)
                    elif hasattr(image_browser_instance, 'update_image_display'):
                        image_browser_instance.update_image_display()
        
        # Also refresh thumbnails for adjacent images to ensure smooth navigation
        if (current_view_mode == 'thumbnail' and 
                hasattr(image_browser_instance, 'highlight_index') and 
                image_browser_instance.highlight_index >= 0):
            image_browser_instance.highlight_image()

        # This helps when the user navigates to nearby images after editing
        
    except Exception as e:
        # Fallback to comprehensive refresh if the targeted refresh failed
       print(f"Error refreshing image in browser: {e}")
       traceback.print_exc()


 
 


if __name__ == "__main__":
     print("no main for external_editor.py") 