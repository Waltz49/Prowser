#!/usr/bin/env python
"""
Native Image Browser - Main Entry Point
Based on the web implementation with enhanced native features
"""

# Enable faulthandler for better crash debugging
import faulthandler
import signal
# ##  DO NOT REMOVE THIS COMMENT: #############################################################################################
#  --- use the followig to profile the code as it runs ---
# bbkill; python -m cProfile -o profile.stats main.py -l 0 /Volumes/MiscFS/&
#
# python -c "
# import pstats
# p = pstats.Stats('profile.stats')
# p.sort_stats('cumulative')
# p.print_stats(30)
# " |sort -rnk 1|less

#  --- use the followig to capture hang traces ---
# printf "bt all\nq\n"|lldb -p $(pgrep -f main.py)
#
#  --- use the followig to capture memory usage on macOS ---
# vmmap -summary $(pgrep -f python.*main.py)
#
#  --- use the followig to capture CPU usage ---
# ps aux | grep main.py | grep -v grep | awk '{print $2}' | xargs -I {} ps -p {} -o %cpu= | awk '{sum+=$1} END {print sum}'
#
#  --- use the followig to capture network usage ---
# ##############################################################################################################################
faulthandler.enable()

# Register USR1 to dump all threads to /tmp/prowserfault.log and the console when signal is received
def dump_threads_on_signal(signum, frame):
    with open('/tmp/prowserfault.log', 'a') as f:
        f.write("=" * 70 + "\n")
        f.write(f"Timestamp: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
        faulthandler.dump_traceback(file=f, all_threads=True)
    # Also write the traceback to the console (stderr)
    faulthandler.dump_traceback(file=None, all_threads=True)

signal.signal(signal.SIGUSR1, dump_threads_on_signal)

# python -m trace --ignore-dir=$(python -c 'import sys; print(":".join(sys.path[1:]))') --trace main.py

# Standard library imports
import argparse
import fnmatch
import json
import logging
import multiprocessing
import os
import shutil
import subprocess
import sys


def _setup_frozen_worker_logging() -> None:
    """Route worker stdout to the shared print log (Tools > Debug > View log)."""
    try:
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass and meipass not in sys.path:
            sys.path.insert(0, meipass)
        from pyinstaller_frozen_support import configure_frozen_native_paths, log_frozen_diagnostic

        configure_frozen_native_paths()
        from print_log_redirect import setup_stdout_print_log

        setup_stdout_print_log(truncate=False)
        log_frozen_diagnostic(
            f"[frozen-worker] started argv={sys.argv!r} _MEIPASS={meipass!r}"
        )
    except Exception as e:
        try:
            print(f"[frozen-worker] logging setup failed: {e}", flush=True)
        except Exception:
            pass


def _frozen_subprocess_bootstrap() -> None:
    """Handle worker flags on the PyInstaller binary (no Qt)."""
    if not getattr(sys, "frozen", False):
        return
    if len(sys.argv) >= 2 and sys.argv[1] == "--model-tasks-worker":
        _setup_frozen_worker_logging()
        from workers.model_tasks_worker import main as model_tasks_main

        raise SystemExit(model_tasks_main())
    if len(sys.argv) >= 3 and sys.argv[1] == "--imagegen-worker":
        _setup_frozen_worker_logging()
        from imagegen_plugins.image_gen_worker_entry import run_worker_main

        raise SystemExit(run_worker_main(sys.argv[2]))
    if len(sys.argv) >= 2 and sys.argv[1] == "--test-create-deps":
        _setup_frozen_worker_logging()
        try:
            from pyinstaller_frozen_support import diffusers_is_installed, mflux_is_installed

            print(f"frozen={getattr(sys, 'frozen', False)}", flush=True)
            print(f"mflux={mflux_is_installed()}", flush=True)
            print(f"diffusers={diffusers_is_installed()}", flush=True)
            try:
                from diffusers import SanaSprintPipeline

                print(f"SanaSprintPipeline={SanaSprintPipeline}", flush=True)
            except Exception as e:
                print(f"SanaSprintPipeline_import_error={e!r}", flush=True)
        except Exception as e:
            import traceback

            traceback.print_exc()
        raise SystemExit(0)


_frozen_subprocess_bootstrap()

import threading
import time
import traceback
import urllib.parse
from typing import List, Dict, Any, Optional

# Disable Qt accessibility warnings
os.environ['QT_ACCESSIBILITY'] = '0'

# Suppress Qt _pythonToCppCopy warnings early by filtering stderr
# These messages come from Qt C++ code and may bypass Python's message handlers
# Install filter BEFORE any Qt imports
_original_stderr_write = sys.stderr.write
_stderr_buffer = ""

def _filtered_stderr_write(text):
    """Filter stderr to suppress _pythonToCppCopy messages and Qt MIME type warnings"""
    global _stderr_buffer
    if not text:
        return
    
    # Convert to string for reliable checking
    text_str = str(text) if not isinstance(text, str) else text
    
    # Always check the incoming text first for patterns to suppress (case-insensitive)
    if '_pythonToCppCopy' in text_str and 'KeyboardModifier' in text_str:
        # Suppress this text completely
        return
    
    # Suppress Qt MIME type ambiguity warnings
    if 'QMimeXMLProvider' in text_str and 'MimeType is ambiguous' in text_str:
        # Suppress this text completely
        return
    
    # Buffer text to handle partial writes (Qt may write in chunks)
    _stderr_buffer += text_str
    
    # Check if we have a complete line
    if '\n' in _stderr_buffer:
        lines = _stderr_buffer.split('\n')
        _stderr_buffer = lines[-1]  # Keep incomplete line
        for line in lines[:-1]:
            # Suppress filtered patterns
            if '_pythonToCppCopy' in line and 'KeyboardModifier' in line:
                continue  # Suppress
            if 'QMimeXMLProvider' in line and 'MimeType is ambiguous' in line:
                continue  # Suppress
            _original_stderr_write(line + '\n')
    # Check if buffer contains the message pattern (for partial writes)
    elif ('_pythonToCppCopy' in _stderr_buffer and 'KeyboardModifier' in _stderr_buffer) or \
         ('QMimeXMLProvider' in _stderr_buffer and 'MimeType is ambiguous' in _stderr_buffer):
        # Found a message pattern in buffer, suppress it
        # Don't write anything, just keep buffering until we see a newline
        if '\n' in text_str:
            # Message ends with newline, clear buffer
            _stderr_buffer = ""
        return
    # For text without the pattern, write it immediately if no buffering needed
    elif '\n' in text_str:
        # Complete line without pattern, write it
        _original_stderr_write(text_str)
        _stderr_buffer = ""
    # Otherwise, text is buffered and will be written when we see a newline

# Install filtered stderr early (before any Qt imports that might trigger messages)
sys.stderr.write = _filtered_stderr_write

# Add the current directory to the Python path so we can import local modules (before print log setup)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Redirect print() (stdout) to one chmod-600 file per uid under tmp; tee to terminal.
from print_log_redirect import setup_stdout_print_log

setup_stdout_print_log(truncate=True)

# Third-party imports
import psutil
from PySide6.QtCore import QEvent, QLoggingCategory, QObject, QTimer
from PySide6.QtGui import QClipboard, QFont, QFontDatabase, QIcon
from PySide6.QtWidgets import QApplication, QFileDialog

# Configure logging to suppress PIL debug messages
logging.getLogger('PIL.Image').setLevel(logging.WARNING)
logging.getLogger('PIL.TiffImagePlugin').setLevel(logging.WARNING)
logging.getLogger('PIL.PngImagePlugin').setLevel(logging.WARNING)
logging.getLogger('PIL.JpegImagePlugin').setLevel(logging.WARNING)
logging.getLogger('PIL.WebPImagePlugin').setLevel(logging.WARNING)
logging.getLogger('PIL.GifImagePlugin').setLevel(logging.WARNING)
logging.getLogger('PIL.BmpImagePlugin').setLevel(logging.WARNING)

# Suppress Qt accessibility messages that come through Python logging
class QtAccessibilityFilter(logging.Filter):
    """Filter to suppress Qt accessibility messages"""
    def filter(self, record):
        return not (hasattr(record, 'name') and 'qt.accessibility' in str(record.name).lower())

# Apply filter to root logger to catch all Qt messages
logging.getLogger().addFilter(QtAccessibilityFilter())

# Local imports
from config import ImageBrowserConfig, get_config
from image_browser_window import ImageBrowserWindow
from thumbnails.thumbnail_constants import (
    BLUE, CYAN, GREEN, LIGHT_GRAY, MAGENTA, RED, RESET, WHITE, YELLOW,
    get_image_extensions,
)
from theme.theme_service import apply_theme, connect_system_theme_listener
from utils import (
    set_main_window,
    convert_file_url_to_path,
    validate_image_file,
    resolve_path,
    validate_path_exists,
    directory_has_images
)

# Note: QtMacExtras was removed from PySide6 (it was PySide5 only)
# QMacNativeEventFilter is no longer available in PySide6
QMacNativeEventFilter = None


class AppleEventsHandler:
    """Handle Apple Events for document-based application"""

    def __init__(self):
        self.received_files = []
        self.event_filter = None
        if QMacNativeEventFilter is not None:
            try:
                self.event_filter = QMacNativeEventFilter()
                # Note: In a real implementation, you'd connect this to handle Apple Events
            except Exception:
                pass

    def get_files_from_apple_events(self):
        """Try to get file paths from Apple Events (macOS document-based application)"""

        try:
            # Method 1: Check if we're in the root directory (typical for Finder launches)
            if os.getcwd() == '/':
                # Try to get the file from the macOS recent files
                try:
                    # Check if there's a file in the recent files that was just opened
                    recent_files = self.get_recently_opened_files()
                    if recent_files:
                        return recent_files
                except Exception:
                    pass

                # Method 2: Try to get the file from the macOS pasteboard (this often works for file associations)
                try:
                    clipboard = QApplication.clipboard()
                    clipboard_text = clipboard.text(QClipboard.Mode.Clipboard)
                    if clipboard_text and clipboard_text.strip():
                        potential_file = clipboard_text.strip()
                        if os.path.exists(potential_file) and os.path.isfile(potential_file):
                            return [potential_file]
                except Exception:
                    pass

                # Method 3: Check if there's a file in the Desktop that was recently accessed
                # (macOS asked for Desktop access, so there might be a file there)
                desktop_dir = os.path.expanduser("~/Desktop")
                if os.path.exists(desktop_dir):
                    image_extensions = get_image_extensions()
                    recent_files = []
                    try:
                        for filename in os.listdir(desktop_dir):
                            file_path = os.path.join(desktop_dir, filename)
                            if os.path.isfile(file_path):
                                _, ext = os.path.splitext(filename)
                                if ext.lower() in image_extensions:
                                    # Check if file was accessed in the last 30 seconds
                                    if time.time() - os.path.getatime(file_path) < 30:  # 30 seconds
                                        recent_files.append(file_path)

                        # Sort by access time, most recent first
                        recent_files.sort(key=lambda x: os.path.getatime(file_path), reverse=True)

                        if recent_files:
                            return [recent_files[0]]
                    except Exception:
                        pass

                # Fallback: Check Downloads for recent image files
                downloads_dir = os.path.expanduser("~/Downloads")
                if os.path.exists(downloads_dir):
                    image_extensions = get_image_extensions()
                    recent_files = []
                    try:
                        for filename in os.listdir(downloads_dir):
                            file_path = os.path.join(downloads_dir, filename)
                            if os.path.isfile(file_path):
                                _, ext = os.path.splitext(filename)
                                if ext.lower() in image_extensions:
                                    recent_files.append(file_path)

                        # Sort by modification time, most recent first
                        recent_files.sort(key=lambda x: os.path.getmtime(file_path), reverse=True)

                        if recent_files:
                            return [recent_files[0]]
                    except Exception:
                        pass

            # Method 4: Check environment variables that might contain file paths
            for key, value in os.environ.items():
                if 'file' in key.lower() and value and os.path.exists(value):
                    return [value]

        except Exception:
            pass

        return []

    def get_recently_opened_files(self):
        """Get recently opened files from macOS"""
        try:
            # Try to get files from the macOS recent files database
            # This is a simplified approach - in a real implementation, you'd use proper Apple Events

            # Check if there are any files in the Desktop or Downloads that were recently modified
            recent_dirs = [
                os.path.expanduser("~/Desktop"),
                os.path.expanduser("~/Downloads"),
                os.path.expanduser("~/Pictures")
            ]

            image_extensions = get_image_extensions()
            recent_files = []

            for directory in recent_dirs:
                if os.path.exists(directory):
                    try:
                        for filename in os.listdir(directory):
                            file_path = os.path.join(directory, filename)
                            if os.path.isfile(file_path):
                                _, ext = os.path.splitext(filename)
                                if ext.lower() in image_extensions:
                                    # Check if file was modified in the last 5 minutes
                                    if time.time() - os.path.getmtime(file_path) < 300:  # 5 minutes
                                        recent_files.append(file_path)
                    except Exception:
                        pass

            # Sort by modification time, most recent first
            recent_files.sort(key=lambda x: os.path.getmtime(file_path), reverse=True)

            return recent_files[:1]  # Return only the most recent file

        except Exception:
            return []


def try_get_file_from_system():
    """Try to get the file path from the system using various methods"""
    try:
        # Method 1: Try to get the file from the macOS pasteboard
        clipboard = QApplication.clipboard()
        clipboard_text = clipboard.text(QClipboard.Mode.Clipboard)
        if clipboard_text and clipboard_text.strip():
            potential_file = clipboard_text.strip()
            if os.path.exists(potential_file) and os.path.isfile(potential_file):
                return potential_file

        # Method 2: Try to get the file from the macOS recent files
        # This is a more direct approach using the system
        try:
            # Use the macOS 'open' command to get the file that was just opened
            # This is a bit of a hack, but it might work
            result = subprocess.run(['osascript', '-e', 'tell application "System Events" to get name of first process whose frontmost is true'],
                                  capture_output=True, text=True)
            if result.stdout.strip():
                pass  # Could use this for future enhancements
        except Exception:
            pass

        # Method 3: Check if there's a file in the Desktop that was recently accessed
        desktop_dir = os.path.expanduser("~/Desktop")
        if os.path.exists(desktop_dir):
            image_extensions = get_image_extensions()
            recent_files = []
            try:
                for filename in os.listdir(desktop_dir):
                    file_path = os.path.join(desktop_dir, filename)
                    if os.path.isfile(file_path):
                        _, ext = os.path.splitext(filename)
                        if ext.lower() in image_extensions:
                            # Check if file was accessed in the last 10 seconds
                            if time.time() - os.path.getatime(file_path) < 10:  # 10 seconds
                                recent_files.append(file_path)

                # Sort by access time, most recent first
                recent_files.sort(key=lambda x: os.path.getatime(file_path), reverse=True)

                if recent_files:
                    return recent_files[0]
            except Exception:
                pass

    except Exception:
        pass

    return None


def signal_handler(signum, frame):
    """Handle system signals for graceful shutdown"""
    handle_application_quit()
    app = QApplication.instance()
    if app:
        app.quit()
    else:
        sys.exit(0)

# Register signal handlers
signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

class FileOpenEventFilter(QObject):
    """Event filter to handle file open events from macOS"""
    
    def __init__(self):
        super().__init__()
        self.app = None
        self.main_window = None
    
    def set_app_and_window(self, app, main_window):
        """Set references to app and main window"""
        self.app = app
        self.main_window = main_window
    
    def eventFilter(self, obj, event):
        """Filter events to catch file open requests"""
        if hasattr(event, 'type') and event.type() == QEvent.FileOpen:
            # Handle file open event from macOS
            file_path = event.file()
            if file_path and os.path.exists(file_path):
                # Convert file:// URL to regular path if needed
                file_path = convert_file_url_to_path(file_path)
                # Open files in the main window, handling filter reset if needed
                self._open_file_in_main_window_mac_reset(file_path)
                return True  # Event handled
        return False  # Let other handlers process the event

    def _open_file_in_main_window_mac_reset(self, file_path):
        """Open a file in the main window, resetting filter if it doesn't match"""
            # Minimum logic for filter reset if not matched
        if self.main_window and hasattr(self.main_window, 'open_specific_file'):
            config = get_config()
            filter_pattern = config.load_settings().get('filter_pattern', '')
            if filter_pattern:
                filename = os.path.basename(file_path)
                normalized_pattern = ImageBrowserConfig.normalize_filter_pattern(filter_pattern)
                if not fnmatch.fnmatch(filename.lower(), normalized_pattern.lower()):
                    # Reset filter per session and config; limit set to 300 for safety window size
                    new_filter = ImageBrowserConfig.normalize_filter_pattern('*')
                    config.update_setting('filter_pattern', new_filter)
                    # Try to make this session filter as well (if main_window expects it passed as arg, must still work)
                    try:
                        if hasattr(self.main_window, 'set_filter_pattern'):
                            self.main_window.set_filter_pattern(new_filter)
                        # else, per session may be handled as part of refresh logic
                    except Exception:
                        pass
            # Now hand off to the opening logic
            self.main_window.open_specific_file(file_path)
        else:
            pass

def parse_arguments():
    """Parse command line arguments"""
    parser = argparse.ArgumentParser(
        description="Prowser - Browse images with thumbnails and fullscreen view",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s /path/to/images          # Open specific directory  
  %(prog)s /path/to/images --filter "image*"  # Show only images matching "image*" pattern
  %(prog)s /path/to/image.jpg  --fullscreen   # Open specific image file in a macOS space (fullscreen)
  %(prog)s /path/to/img1.jpg /path/to/img2.png  # Open multiple specific image files
  %(prog)s /path/to/images/ -p ~/.prowser-test  # Use custom profile directory
        """)
    
    parser.add_argument('paths', nargs='*', help='Directory containing images to browse, or specific image files to open')
    parser.add_argument('-f', '--filter', type=str, metavar='PATTERN',
                        help='Filter images using glob pattern (e.g., "image*", "*.jpg", "IMG_*")')
    parser.add_argument('--fullscreen', action='store_true',
                        help='Launch the window in OS fullscreen mode (default behavior, kept for compatibility)')
    parser.add_argument('--no-fullscreen', action='store_true',
                        help='Launch the window in OS windowed mode (OS fullscreen is default)')
    parser.add_argument('--debug', action='store_true',
                        help='Enable debug mode (hide key popup)')
    parser.add_argument('-p', '--profile', type=str, metavar='DIR',
                        help='Use a custom profile directory instead of ~/.prowser')
    parser.add_argument(
        '--background',
        choices=['default', 'thread', 'process'],
        default='default',
        metavar='MODE',
        help='Run jobs in a thread, process, or default '
             '(thread in app, process from source)',
    )
    parser.add_argument(
        '--min',
        action='store_true',
        help='Simulate a minimal PyInstaller bundle: '
             'hide image generation, LM Studio, voice input, and related UI',
    )
    
    return parser.parse_args()

# Image and path validation functions moved to utils.py
# Imported at top of file

def is_started_from_command_line() -> bool:
    """Check if application was started from command line (not macOS app bundle)"""
    # Check if sys.argv[0] contains .app (indicates app bundle launch)
    if '.app' in sys.argv[0] or '.app/' in sys.argv[0]:
        return False
    # Also check if we're running from a bundle by checking parent process
    try:
        parent = psutil.Process(os.getppid())
        parent_cmd = ' '.join(parent.cmdline()) if hasattr(parent, 'cmdline') else ''
        if '.app' in parent_cmd:
            return False
    except Exception:
        pass
    return True

def build_configuration_message_from_args(args) -> Optional[Dict[str, Any]]:
    """Build a configuration message from command line arguments for pipe communication"""
    message = {}
    
    # Convert paths to absolute paths and validate
    if args.paths:
        resolved_paths = []
        for path in args.paths:
            resolved = resolve_path(path, must_exist=True)
            if resolved:
                resolved_paths.append(resolved)
        
        if not resolved_paths:
            return None
        
        # Determine if paths are files or directories
        files = [p for p in resolved_paths if os.path.isfile(p) and validate_image_file(p)]
        directories = [p for p in resolved_paths if os.path.isdir(p)]
        
        if files:
            # Prefer files over directories (per API spec)
            message['files'] = files
        elif directories:
            message['directory'] = directories[0]
        else:
            return None
    else:
        # No paths provided - don't send message
        return None
    
    # Add optional parameters
    if args.filter is not None:
        message['filter'] = args.filter
    
    return message

def try_send_to_existing_instance(message: Dict[str, Any], pipe_path: str, timeout: float = 4.0) -> bool:
    """
    Try to send configuration to existing instance via pipe.
    Returns True if message was successfully sent (another instance accepted it).
    Returns False if pipe doesn't exist, write times out, or write fails.
    
    Note: Opening a FIFO for writing blocks until a reader opens it.
    If write completes within timeout, another instance is listening.
    If write times out, no instance is listening (pipe is dead).
    """
    if not os.path.exists(pipe_path):
        return False
    
    write_success = False
    write_error = None
    write_completed = threading.Event()
    
    def write_to_pipe():
        nonlocal write_success, write_error
        try:
            # Open pipe for writing (will block until reader opens it)
            # If no reader is present, this will block indefinitely
            with open(pipe_path, 'w') as pipe:
                json.dump(message, pipe)
                pipe.write('\n')
                pipe.flush()
                write_success = True
        except Exception as e:
            write_error = e
        finally:
            write_completed.set()
    
    # Start write in a thread
    write_thread = threading.Thread(target=write_to_pipe, daemon=True)
    write_thread.start()
    
    # Wait up to timeout seconds for write to complete
    write_completed.wait(timeout=timeout)
    
    if not write_completed.is_set():
        # Write is still blocking - no reader available, pipe is likely dead
        # The thread will continue blocking, but we proceed to start new instance
        return False
    
    # Write completed - check if it succeeded
    if write_success:
        # Write succeeded - another instance read the message
        return True
    else:
        # Write failed - pipe might be dead or error occurred
        return False

def handle_application_quit():
    """Enhanced application quit with robust cleanup"""
    # Save current state before cleanup
    global main_window
    if 'main_window' in globals() and main_window:
        try:
            # Save current state for restoration
            config = get_config()
            current_directory = getattr(main_window, 'current_directory', None)
            current_view_mode = getattr(main_window, 'current_view_mode', 'thumbnail')
            
            # Determine the current file based on view mode (same logic as get_current_image_path)
            current_file = None
            if hasattr(main_window, 'displayed_images') and main_window.displayed_images:
                if current_view_mode in ['browse', 'slideshow', 'slideshow2']:
                    # For fullscreen and slideshow modes, use current_index
                    if hasattr(main_window, 'current_index'):
                        current_index = getattr(main_window, 'current_index', -1)
                        if 0 <= current_index < len(main_window.displayed_images):
                            current_file = main_window.displayed_images[current_index]
                elif hasattr(main_window, 'highlight_index'):
                    # For thumbnail mode, use highlight_index
                    highlight_index = getattr(main_window, 'highlight_index', -1)
                    if 0 <= highlight_index < len(main_window.displayed_images):
                        current_file = main_window.displayed_images[highlight_index]
            
            
            # Only save if we have a valid directory or file
            if current_directory or current_file:
                # Save macOS Space vs windowed display mode
                macos_space_mode = getattr(main_window, 'isFullScreen', lambda: False)()
                config.save_restore_state(
                    current_file, current_directory, current_view_mode, macos_space_mode
                )
        except Exception:
            pass  # Don't fail on state saving
        
        try:
            main_window.ensure_cleanup_before_exit()
        except Exception:
            pass
    
    # Clean up KML directory
    try:
        from files.map_manager import cleanup_kml_directory
        cleanup_kml_directory()
    except Exception:
        pass
    
    # Force cleanup of any remaining processes
    current_process = psutil.Process()
    children = current_process.children(recursive=True)
    
    # First, terminate all relevant child processes
    for child in children:
        try:
            if child.name() and 'python' in child.name().lower():
                child.terminate()
        except Exception:
            pass

    # Now check each process, wait, and kill if necessary
    for child in children:
        try:
            if child.name() and 'python' in child.name().lower():
                try:
                    child.wait(timeout=1.0)
                except Exception:
                    pass
                if child.is_running():
                    try:
                        child.kill()
                    except Exception:
                        pass
        except Exception:
            pass
def display_entry_error(message_title:str="Error", message:str="An error occurred"):
    """Display an error message using centralized styled dialog"""
    try:
        from utils import show_styled_critical
        show_styled_critical(None, message_title, message)
        return 0
    except Exception as e:
        print(f"Error creating dialog: {e}")
        traceback.print_exc()
        return 0 

def main():
    # Global reference to the main window for cleanup
    global main_window
    main_window = None
    
    # Parse command line arguments early to get profile directory
    args = parse_arguments()

    if args.min:
        os.environ["PROWSER_MIN_BUNDLE"] = "1"

    from workers.model_tasks_launch import set_background_mode

    set_background_mode(args.background)
    
    # Handle custom profile directory if specified
    profile_dir = None
    if args.profile:
        profile_dir = args.profile
        # Expand user directory if ~ is used
        profile_dir = os.path.expanduser(profile_dir)
        # Resolve to absolute path
        try:
            profile_dir = os.path.abspath(profile_dir)
        except Exception as e:
            print(f"Error resolving profile directory path: {e}")
            sys.exit(1)
        
        # Validate that the parent directory exists (if creating a new directory)
        parent_dir = os.path.dirname(profile_dir)
        if parent_dir and not os.path.exists(parent_dir):
            print(f"Error: Parent directory does not exist: {parent_dir}")
            sys.exit(1)
        
        # Try to create the profile directory if it doesn't exist
        try:
            os.makedirs(profile_dir, exist_ok=True)
        except OSError as e:
            print(f"Error: Cannot create profile directory '{profile_dir}': {e}")
            sys.exit(1)
        
        # Verify we can write to the directory
        if not os.access(profile_dir, os.W_OK):
            print(f"Error: Cannot write to profile directory: {profile_dir}")
            sys.exit(1)
    
    # Clean up log directory before anything else
    try:
        config = get_config(profile_dir=profile_dir)
        logs_dir = config.logs_dir
        if logs_dir.exists():
            shutil.rmtree(logs_dir)
        # Ensure log directory exists after cleanup
        logs_dir.mkdir(exist_ok=True)
        exception_file = "/tmp/exception.txt"
        if os.path.exists(exception_file):
            os.unlink(exception_file)
    except Exception as e:
        traceback.print_exc()
        pass

    # Single instance check: if started from command line, try to send config to existing instance
    if is_started_from_command_line():
        pipe_path = str(config.named_pipe)
        if os.path.exists(pipe_path):
            # Build configuration message from args
            message = build_configuration_message_from_args(args)
            if message:
                # Try to send to existing instance
                if try_send_to_existing_instance(message, pipe_path, timeout=4.0):
                    # Message was accepted by another instance, exit
                    sys.exit(0)
                # Otherwise, pipe is dead or no instance listening, proceed to start new instance

    # Safely get working directory with error handling
    try:
        working_dir = os.getcwd()
    except FileNotFoundError:
        working_dir = os.path.expanduser("~")
        try:
            os.chdir(working_dir)
        except Exception as e:
            working_dir = "/tmp"  # Fallback to /tmp
            try:
                os.chdir(working_dir)
            except Exception as e:
                pass
    
    # Set process name if specified in environment    # Set process name if specified in environment
    if os.environ.get('PROCESS_NAME'):
        try:
            current_process = psutil.Process()
            current_process.name = os.environ['PROCESS_NAME']
        except:
            pass  # Ignore if we can't set process name
    
    # Suppress Qt accessibility logging messages
    QLoggingCategory.setFilterRules("qt.accessibility.*=false")
    
    # Suppress Qt _pythonToCppCopy warnings for KeyboardModifier
    # These warnings occur when Qt tries to copy KeyboardModifier enum values
    # The value like 0x10443aa50 is a memory address (pointer) - harmless but noisy
    # Install a message handler to filter out these specific warnings
    from PySide6.QtCore import qInstallMessageHandler, QtMsgType
    
    # Store original handler
    _original_qt_handler = [None]  # Use list to allow modification in closure
    
    def qt_message_handler(msg_type, context, message):
        """Filter out _pythonToCppCopy warnings for KeyboardModifier"""
        # Suppress _pythonToCppCopy warnings for KeyboardModifier
        # Check both the message string and convert to string to handle different message types
        try:
            message_str = str(message) if message else ""
            # Check for the warning pattern (case-insensitive for robustness)
            if message_str and '_pythonToCppCopy' in message_str and 'KeyboardModifier' in message_str:
                return  # Suppress these warnings
        except Exception:
            # If conversion fails, pass through to original handler
            pass
        
        # For other messages, use default Qt behavior (print warnings/errors to stderr)
        # or call original handler if it exists
        if _original_qt_handler[0]:
            _original_qt_handler[0](msg_type, context, message)
        elif msg_type >= QtMsgType.QtWarningMsg:
            # Use os.write to avoid deadlock: Qt message handler can be invoked from
            # background threads (e.g. _monitor_timestamps). Python's print() uses a
            # buffer lock; main thread may hold it while we need it -> deadlock.
            try:
                msg = (str(message) if message else "") + "\n"
                os.write(sys.stderr.fileno(), msg.encode("utf-8", "replace"))
            except OSError:
                pass
    
    # Install our custom handler and store the original
    _original_qt_handler[0] = qInstallMessageHandler(qt_message_handler)
    
    # Note: stderr filtering is already installed at module level (before Qt imports)
    # This ensures we catch messages that come from Qt C++ code
    
    # Create the application first - before any QWidget operations
    app = QApplication(sys.argv)
    app.setApplicationName("Prowser")
    app.setApplicationDisplayName("Prowser")
    app.setApplicationVersion("0.9.0")
    app.setOrganizationName("ImageBrowser")

    try:
        _theme_cfg = get_config(profile_dir=profile_dir)
    except Exception:
        _theme_cfg = get_config()
    connect_system_theme_listener()
    _ui_theme = _theme_cfg.load_settings().get("ui_theme", "dark")
    apply_theme(_ui_theme, app=app, persist=False, config=_theme_cfg)

    # Connect quit handler to ensure proper cleanup
    app.aboutToQuit.connect(handle_application_quit)

    # Install event filter for handling file open events (macOS document-based app)
    file_open_filter = FileOpenEventFilter()
    app.installEventFilter(file_open_filter)
    
    # Main loop to handle path validation and file dialog
    while True:
        # Convert file:// URLs to regular paths for macOS compatibility
        if args.paths:
            args.paths = [convert_file_url_to_path(path) for path in args.paths]
            seen = set()
            unique_paths = []
            for p in args.paths:
                if p not in seen:
                    seen.add(p)
                    unique_paths.append(p)
            args.paths = unique_paths
        # Handle fullscreen flags: --fullscreen and --no-fullscreen
        # Priority: explicit flags override saved state, default is fullscreen
        explicit_fullscreen_flag = False
        explicit_no_fullscreen_flag = False
        
        # Check if flags were explicitly passed
        if hasattr(args, 'fullscreen') and args.fullscreen:
            explicit_fullscreen_flag = True
        if hasattr(args, 'no_fullscreen') and args.no_fullscreen:
            explicit_no_fullscreen_flag = True
        
        # Determine fullscreen setting based on explicit flags, saved state, or default
        if explicit_fullscreen_flag:
            # --fullscreen explicitly passed: force fullscreen
            args.no_fullscreen = False
        elif explicit_no_fullscreen_flag:
            # --no-fullscreen explicitly passed: force windowed
            args.no_fullscreen = True
        else:
            # No explicit flags: check saved state for last macOS Space vs windowed preference
            config = get_config()
            restore_state = config.get_restore_state()
            if restore_state:
                last_macos_space_mode = restore_state.get('last_macos_space_mode')
                if last_macos_space_mode is not None:
                    args.no_fullscreen = not last_macos_space_mode
                else:
                    args.no_fullscreen = False
            else:
                args.no_fullscreen = False
        
        # Track if we have explicit flags (for later override of saved state)
        args._explicit_fullscreen_flag = explicit_fullscreen_flag
        args._explicit_no_fullscreen_flag = explicit_no_fullscreen_flag
        
        # If no paths provided, check for saved state or macOS document-based application file opening
        if not args.paths:
            # First, try to restore from saved state
            # restore_state already retrieved above if no explicit flags, retrieve again if needed
            if 'restore_state' not in locals():
                if 'config' not in locals():
                    config = get_config()
                restore_state = config.get_restore_state()
            
            if restore_state:
                # We have saved state, restore it
                last_file = restore_state.get('last_file')
                last_directory = restore_state.get('last_directory')
                last_view_mode = restore_state.get('last_view_mode', 'thumbnail')


                # Store restore state for later use after window creation
                args._restore_state = restore_state
                
                # Only respect saved state if no explicit flags were passed
                if not explicit_fullscreen_flag and not explicit_no_fullscreen_flag:
                    # No explicit flags: args.no_fullscreen already set from saved OS fullscreen state above
                    # Just restore the paths
                    if last_file and os.path.exists(last_file):
                        args.paths = [last_file]
                    elif last_directory and os.path.exists(last_directory):
                        # Restore directory
                        args.paths = [last_directory]
                else:
                    # Explicit flags override saved state: use paths from saved state but respect flags
                    if last_file and os.path.exists(last_file):
                        args.paths = [last_file]
                    elif last_directory and os.path.exists(last_directory):
                        args.paths = [last_directory]
                    # args.no_fullscreen already set by explicit flag handling above
                    print(f"Last directory: {last_directory}")

                    # Use utility function for directory image checking
                    dir_has_supported_files = directory_has_images

                    # If the last saved file does not exist, but the last directory exists and has supported files, just show the directory
                    if not (last_file and os.path.exists(last_file)) and os.path.exists(last_directory) and dir_has_supported_files(last_directory):
                        print(f"Last file does not exist, but last directory has supported image files, using directory: {last_directory}")
                        args.paths = [last_directory]
                    elif dir_has_supported_files(last_directory):
                        print(f"Last directory has supported image files, using it")
                        args.paths = [last_directory]
                    else:
                        # Open the system directory dialog and set args.paths from the result, or exit if canceled
                        args.paths = open_directory_dialog(args)
            else:
                # No saved state, try macOS document-based application file opening
                # Create Apple Events handler
                apple_events_handler = AppleEventsHandler()
                
                # Try the new system method first
                system_file = try_get_file_from_system()
                if system_file:
                    args.paths = [system_file]
                else:
                    # Fallback to the Apple Events method
                    apple_event_files = apple_events_handler.get_files_from_apple_events()
                    if apple_event_files:
                        args.paths = apple_event_files
                    else:
                        # Fallback to current directory
                        current_dir = os.getcwd()
                        if current_dir == '/':
                            # If we're in root directory, try to use a more sensible default
                            current_dir = os.path.expanduser("~/Pictures")
                            if not os.path.exists(current_dir):
                                current_dir = os.path.expanduser("~/Downloads")
                            if not os.path.exists(current_dir):
                                current_dir = os.path.expanduser("~")
                        
                        args.paths = [current_dir]
        
        # Validate all paths exist and resolve to absolute paths
        resolved_paths = []
        validation_failed = False
        error_message = ""
        
        for path in args.paths:
            resolved = resolve_path(path, must_exist=True)
            if not resolved:
                validation_failed = True
                error_message = f"Path does not exist: {path}"
                break
            
            resolved_paths.append(resolved)
        
        # If validation failed, show error and file dialog
        if validation_failed:
            print(f"Validation failed: {error_message}")
            try:
                # Show file dialog to get new selection
                args.paths = open_directory_dialog(args)
                continue  # Try again with new paths
            except SystemExit:
                return 0  # User canceled dialog
        
        # Update args.paths with resolved paths
        args.paths = resolved_paths
        def get_actual_cased_path(path):
            # Fast path: skip per-segment listdir when the path already resolves.
            # Case correction is cosmetic on macOS; listdir per segment is very slow on network volumes.
            abs_path = os.path.abspath(path)
            if os.path.exists(abs_path):
                return abs_path
            # Split into segments
            segments = []
            head, tail = os.path.split(abs_path)
            while tail:
                segments.insert(0, tail)
                head, tail = os.path.split(head)
            # At this point, head is root or empty
            actual_path = head if head else os.sep
            for segment in segments:
                try:
                    entries = os.listdir(actual_path)
                except Exception:
                    # If any failure, fallback to original
                    actual_path = os.path.join(actual_path, segment)
                    continue
                segment_actual = next((e for e in entries if e.lower() == segment.lower()), segment)
                actual_path = os.path.join(actual_path, segment_actual)
            return actual_path
        # Determine the mode based on number of paths and their types
        args.paths = [get_actual_cased_path(path) for path in args.paths]
        target_files: List[str] = []
        directory = None
        mode_validation_failed = False
        
        if len(args.paths) == 1:
            # Single path - can be file or directory
            path = args.paths[0]
            if os.path.isfile(path):
                # Single file
                if not validate_image_file(path):
                    mode_validation_failed = True
                    error_message = f"File is not a supported image format: {path}"
                else:
                    # If we're restoring thumbnail/slideshow mode, use directory instead of file
                    if hasattr(args, '_restore_state') and args._restore_state:
                        restore_state = args._restore_state
                        last_view_mode = restore_state.get('last_view_mode', 'thumbnail')
                        if last_view_mode in ['thumbnail', 'slideshow', 'slideshow2']:
                            # Use directory instead of file to avoid fullscreen view
                            directory = os.path.dirname(path)
                            target_files = []  # Don't set target_files, use directory instead
                        else:
                            target_files = [path]
                            directory = os.path.dirname(path)
                    else:
                        target_files = [path]
                        directory = os.path.dirname(path)
                    
                    # When opening a specific file, enable OS fullscreen mode by default
                    # But only if we're not restoring thumbnail/slideshow mode
                    # And only if no explicit flags were passed
                    if not getattr(args, '_explicit_fullscreen_flag', False) and not getattr(args, '_explicit_no_fullscreen_flag', False):
                        if not args.no_fullscreen:
                            if not (hasattr(args, '_restore_state') and args._restore_state and 
                                    args._restore_state.get('last_view_mode', 'thumbnail') in ['thumbnail', 'slideshow', 'slideshow2']):
                                args.no_fullscreen = False  # Keep fullscreen as default
                        
            elif os.path.isdir(path):
                # Single directory
                directory = path
                # Track if this directory came from command line (not restoration)
                # If it came from command line, we should open in thumbnail mode
                # If it came from restoration, we should restore the saved view mode
                # Check if we're restoring by seeing if _restore_state exists OR if args.no_fullscreen
                # was set from saved state (which happens at lines 454-457 when restoring)
                has_restore_state_at_check = hasattr(args, '_restore_state') and args._restore_state
                # Also check if we're in the restoration flow by checking if we have no explicit flags
                # and args.no_fullscreen was set (indicating it came from saved state)
                is_restoration_flow = (not explicit_fullscreen_flag and 
                                      not explicit_no_fullscreen_flag and
                                      hasattr(args, 'no_fullscreen'))
                
                if has_restore_state_at_check or is_restoration_flow:
                    # Directory from restoration - allow restoring browse view if that was saved
                    args._directory_from_command_line = False
                else:
                    # Directory from command line - mark it so we don't restore browse view
                    args._directory_from_command_line = True
            else:
                mode_validation_failed = True
                error_message = f"Path is neither a file nor a directory: {path}"
        
        else:
            # Multiple paths - all must be files
            for path in args.paths:
                if os.path.isdir(path):
                    mode_validation_failed = True
                    error_message = f"When specifying multiple paths, all must be files. Directory found: {path}"
                    break
                
                if not os.path.isfile(path):
                    mode_validation_failed = True
                    error_message = f"Path is not a file: {path}"
                    break
                
                if not validate_image_file(path):
                    mode_validation_failed = True
                    error_message = f"File is not a supported image format: {path}"
                    break
            
            if not mode_validation_failed:
                # All paths are valid image files
                target_files = args.paths
                # Use the directory of the first file as the base directory
                try:
                    directory = os.path.dirname(target_files[0])
                except Exception:
                    directory = os.path.expanduser("~")
                
                # When opening multiple files, enable OS fullscreen mode by default
                # But only if no explicit flags were passed
                if not getattr(args, '_explicit_fullscreen_flag', False) and not getattr(args, '_explicit_no_fullscreen_flag', False):
                    if not args.no_fullscreen:
                        args.no_fullscreen = False  # Keep fullscreen as default
        
        # If mode validation failed, show error and file dialog
        if mode_validation_failed:
            print(f"Mode validation failed: {error_message}")
            try:
                # Show file dialog to get new selection
                args.paths = open_directory_dialog(args)
                continue  # Try again with new paths
            except SystemExit:
                return 0  # User canceled dialog
        
        # If we get here, validation passed - break out of the loop
        break
    
    # Set default font to prevent Qt font resolution delays
    # Get available font families using static method to avoid deprecation warning
    font_families = QFontDatabase.families()
    
    # Choose an appropriate font family for macOS
    selected_font_family = None
    # Try common macOS fonts in order of preference
    for font_name in ["Helvetica Neue", "Helvetica", "Arial"]:
        if font_name in font_families:
            selected_font_family = font_name
            break
    
    # Only set font if we found a valid one
    if selected_font_family:
        font = QFont(selected_font_family)
        app.setFont(font)
        # Also set a default font family to avoid Sans-serif lookup
        QApplication.setDesktopSettingsAware(False)  # Prevent Qt from looking up system fonts
    
    # Set application icon if available
    icon_path = os.path.join(os.path.dirname(__file__), "assets", "icon.png")
    if os.path.exists(icon_path):
        app.setWindowIcon(QIcon(icon_path))
    
    # Create and show the main window
    try:
        # Load saved settings first, then override with command line arguments
        config = get_config()
        saved_settings = config.load_settings()
        
        window_filter = args.filter if args.filter is not None else saved_settings.get('filter_pattern', '')
        if window_filter:
            window_filter = ImageBrowserConfig.normalize_filter_pattern(window_filter)
        else:
            window_filter = None
        if config.get_restore_state():
            lvm = config.get_restore_state().get('last_view_mode', 'thumbnail')
        else:
            lvm = 'thumbnail'
        
        # Determine immediate_macos_space_mode: respect explicit flags, saved state, or default
        is_directory_only = directory and not target_files
        
        if is_directory_only:
            immediate_macos_space_mode = False
        elif getattr(args, '_explicit_no_fullscreen_flag', False):
            immediate_macos_space_mode = False
        elif getattr(args, '_explicit_fullscreen_flag', False):
            immediate_macos_space_mode = True
        else:
            immediate_macos_space_mode = not args.no_fullscreen
        
        window = ImageBrowserWindow(
            fullscreen=not args.no_fullscreen if not is_directory_only else False,
            target_file=None,  # We'll handle this via configuration
            immediate_macos_space_mode=immediate_macos_space_mode, 
            debug_mode=args.debug,
            filter_pattern=window_filter
        )
        
        # Store global reference for cleanup
        main_window = window
        set_main_window(window)
        
        # Connect file open filter to main window for macOS document handling
        if file_open_filter:
            file_open_filter.set_app_and_window(app, window)
        
        # Create configuration based on command line arguments
        configuration = {}
        
        # Add fullscreen flags to configuration
        # Priority: explicit flags > saved state > default (fullscreen)
        if hasattr(args, '_restore_state') and args._restore_state:
            # We're restoring state
            restore_state = args._restore_state
            last_view_mode = restore_state.get('last_view_mode', 'thumbnail')
            configuration['restore_view_mode'] = last_view_mode
            
            # Check if explicit flags override saved state
            if getattr(args, '_explicit_fullscreen_flag', False):
                # --fullscreen explicitly passed: force OS fullscreen
                configuration['fullscreen'] = True
                configuration['prevent_browse_view'] = False
            elif getattr(args, '_explicit_no_fullscreen_flag', False):
                # --no-fullscreen explicitly passed: force windowed
                configuration['fullscreen'] = False
                configuration['prevent_browse_view'] = True
            else:
                # No explicit flags: use args.no_fullscreen which was set from saved state
                # args.no_fullscreen is already set correctly from restoration logic above
                configuration['fullscreen'] = not args.no_fullscreen
                configuration['prevent_browse_view'] = args.no_fullscreen
        else:
            # No saved state: use explicit flags or default to fullscreen
            if getattr(args, '_explicit_no_fullscreen_flag', False):
                configuration['fullscreen'] = False
                configuration['prevent_browse_view'] = True
            elif getattr(args, '_explicit_fullscreen_flag', False):
                configuration['fullscreen'] = True
                configuration['prevent_browse_view'] = False
            else:
                # Default: fullscreen (either explicit --fullscreen or no flags)
                configuration['fullscreen'] = True
        # Save command line parameters to configuration if provided
        if args.filter is not None:
            # Normalize filter pattern for storage (remove trailing asterisk)
            normalized_filter = ImageBrowserConfig.normalize_filter_pattern(args.filter)
            config.update_setting('filter_pattern', normalized_filter)
        
        if target_files:
            # Load specific files
            configuration['files'] = target_files
            # Apply filter for specific files if provided
            if args.filter is not None:
                configuration['filter'] = args.filter
            
            # Check if any target files don't match the current filter pattern
            # If so, reset the filter to show all images for this session
            if window_filter:
                filter_matches_all_files = True
                for file_path in target_files:
                    filename = os.path.basename(file_path)
                    if not fnmatch.fnmatch(filename.lower(), window_filter.lower()):
                        filter_matches_all_files = False
                        break
                
                if not filter_matches_all_files:
                    # Reset filter for this session to show all images
                    window_filter = None
                    configuration['filter_pattern'] =  ImageBrowserConfig.normalize_filter_pattern('*')
                    config.update_setting('filter_pattern', configuration['filter_pattern']) # DGN persistance may not be necessary
                    print(f"{YELLOW}Target files don't match current filter pattern. Resetting filter to show all images for this session.{RESET}")
        elif directory:
            # Load directory
            configuration['directory'] = directory
            # When opening a directory from command line (not restoration), start in thumbnail mode
            # But if restoring from saved state, allow restoring browse view if that was saved
            # IMPORTANT: --fullscreen flag should override directory defaults
            directory_from_command_line = getattr(args, '_directory_from_command_line', False)
            explicit_fullscreen = getattr(args, '_explicit_fullscreen_flag', False)
            
            # Check if we're restoring from saved state by checking if args.no_fullscreen was set from saved state
            # We know we're restoring if:
            # 1. We don't have explicit flags (no --fullscreen or --no-fullscreen)
            # 2. args.no_fullscreen exists and was set (it's set from saved state at lines 454-457)
            # 3. directory_from_command_line is False (meaning it came from restoration, not command line)
            is_restoring_state = (not explicit_fullscreen and 
                                not getattr(args, '_explicit_no_fullscreen_flag', False) and
                                not directory_from_command_line and
                                hasattr(args, 'no_fullscreen'))
            
            if directory_from_command_line:
                # Directory from command line: prevent browse view, ensure thumbnail mode
                # BUT: respect --fullscreen flag if explicitly passed
                configuration['prevent_browse_view'] = True
                if not explicit_fullscreen:
                    # Only set fullscreen=False if --fullscreen was NOT explicitly passed
                    configuration['fullscreen'] = False
                else:
                    # --fullscreen explicitly passed: keep fullscreen=True
                    configuration['fullscreen'] = True
            elif is_restoring_state:
                # Directory from restoration: ALWAYS set fullscreen from saved state
                # args.no_fullscreen was already set correctly from saved state at lines 454-457
                configuration['fullscreen'] = not args.no_fullscreen
                configuration['prevent_browse_view'] = args.no_fullscreen
            else:
                # Default case: not from command line, not restoring state
                # Use defaults (fullscreen for single files, windowed for directories)
                configuration['prevent_browse_view'] = True
                configuration['fullscreen'] = False
            if args.filter is not None:
                configuration['filter'] = args.filter

        if window.debug_mode:
            from debug_log import debug_timestamp

            print(f"\n{debug_timestamp()} Window.show is starting with configuration: {CYAN}{configuration}{RESET}")
       
        else:
            print(f"\nWindow.show is starting with configuration: {CYAN}{configuration}{RESET}")
       
        window.show()
        
        # Activate and raise window to ensure it's ready for fullscreen
        window.activateWindow()
        window.raise_()
        
        # If --fullscreen was explicitly passed OR restoring from fullscreen state,
        # also try entering fullscreen directly here as a backup
        # in case refresh_from_configuration doesn't handle it
        # BUT: respect --no-fullscreen flag - it should prevent fullscreen
        should_restore_macos_space_mode = False
        if getattr(args, '_explicit_no_fullscreen_flag', False):
            should_restore_macos_space_mode = False
        elif getattr(args, '_explicit_fullscreen_flag', False):
            should_restore_macos_space_mode = True
        elif hasattr(args, '_restore_state') and args._restore_state:
            restore_state = args._restore_state
            last_macos_space_mode = restore_state.get('last_macos_space_mode')
            if last_macos_space_mode is True:
                should_restore_macos_space_mode = True
        
        if should_restore_macos_space_mode:
            def try_macos_space_mode_direct():
                if not window.isFullScreen() and window.isVisible():
                    window.enter_macos_space_mode()
            QTimer.singleShot(300, try_macos_space_mode_direct)
        
        # Set focus on the main pane immediately (menu shortcut priming is deferred
        # until after initial layout — see MenuManager.schedule_startup_menu_shortcut_priming).
        def ensure_startup_focus():
            try:
                if hasattr(window, 'main_content_widget'):
                    window.main_content_widget.setFocus()
                elif hasattr(window, 'focus_canvas'):
                    window.focus_canvas()
                window.activateWindow()
                window.raise_()
            except Exception:
                traceback.print_exc()
        
        ensure_startup_focus()
        QTimer.singleShot(50, ensure_startup_focus)

        # Refresh the browser with the configuration after window is shown
        if configuration:
            # Use a longer delay to ensure the window is fully initialized
            def delayed_refresh():
                try:
                    config.update_setting('current_view_mode', lvm) # probably not needed
                    window.refresh_from_configuration(configuration)
                    
                    # Immediately ensure correct view mode if restoring thumbnail/slideshow
                    if hasattr(args, '_restore_state') and args._restore_state:
                        restore_state = args._restore_state
                        last_view_mode = restore_state.get('last_view_mode', 'thumbnail')
                        if last_view_mode in ['thumbnail', 'slideshow', 'slideshow2']:
                            # Ensure we're in thumbnail view, not fullscreen view
                            if window.current_view_mode != 'thumbnail':
                                window.view_manager.close_browse_view()
                    
                    # Restore view mode if we have saved state
                    # BUT: Don't restore browse view when a directory is explicitly provided on command line
                    # If directory came from restoration, we should restore the saved view mode (including browse)
                    # Check if we're opening a directory (not a specific file)
                    is_directory_only = 'directory' in configuration and 'files' not in configuration
                    # Check if directory came from command line (not restoration)
                    directory_from_command_line = getattr(args, '_directory_from_command_line', False)
                    
                    if hasattr(args, '_restore_state') and args._restore_state and (not is_directory_only or not directory_from_command_line):
                        # Only restore state when NOT opening a directory
                        restore_state = args._restore_state
                        last_view_mode = restore_state.get('last_view_mode', 'thumbnail')
                        last_file = restore_state.get('last_file')
                        
                        # Wait a bit more for directory/images to load
                        def restore_view_mode():
                            try:
                                # Ensure we have displayed_images before proceeding
                                if not hasattr(window, 'displayed_images') or not window.displayed_images:
                                    return
                                
                                # Find the image index if last_file exists and is in displayed_images
                                image_index = None
                                if last_file and os.path.exists(last_file):
                                    try:
                                        image_index = window.displayed_images.index(last_file)
                                    except (ValueError, IndexError):
                                        image_index = 0 if window.displayed_images else None
                                else:
                                    image_index = 0 if window.displayed_images else None
                                
                                # Don't try to set highlight/current_index if displayed_images is empty
                                if image_index is None or not window.displayed_images or len(window.displayed_images) == 0:
                                    # On a new machine or empty directory, displayed_images is empty.
                                    # Avoid index errors. Optionally, may show a "No images found" popup here.
                                    return
                                
                                if last_view_mode in ['slideshow', 'slideshow2']:
                                    # Slideshow: restore to thumbnails with current image highlighted
                                    if window.current_view_mode != 'thumbnail':
                                        window.view_manager.close_browse_view()
                                    window.highlight_index = image_index
                                    window.current_index = image_index
                                    window.current_image_path = window.displayed_images[image_index]
                                    window.highlight_image()
                                elif last_view_mode == 'browse':
                                    # Restore browse view if:
                                    # 1. We're NOT opening a directory-only configuration, OR
                                    # 2. The directory came from restoration (not command line)
                                    # This allows restoring browse view when restoring from saved state,
                                    # but prevents it when user explicitly opens a directory from command line
                                    if not is_directory_only or not directory_from_command_line:
                                        if not args.no_fullscreen:
                                            window.view_mode_manager.open_browse_view(image_index)
                                        else:
                                            if window.current_view_mode != 'thumbnail':
                                                window.view_manager.close_browse_view()
                                            window.highlight_index = image_index
                                            window.current_index = image_index
                                            window.current_image_path = window.displayed_images[image_index]
                                            window.highlight_image()
                                    else:
                                        # Opening a directory from command line: stay in thumbnail mode
                                        if window.current_view_mode != 'thumbnail':
                                            window.view_manager.close_browse_view()
                                        window.current_view_mode = 'thumbnail'
                                        window.highlight_index = image_index if image_index is not None else 0
                                        window.current_index = image_index if image_index is not None else 0
                                        if window.displayed_images:
                                            window.current_image_path = window.displayed_images[window.current_index]
                                            window.highlight_image()
                                else:  # thumbnail
                                    if window.current_view_mode != 'thumbnail':
                                        window.view_manager.close_browse_view()
                                    window.highlight_index = image_index
                                    window.current_index = image_index
                                    window.current_image_path = window.displayed_images[image_index]
                                    window.highlight_image()
                            except Exception:
                                import traceback
                                traceback.print_exc()
                                pass
                        
                        QTimer.singleShot(300, restore_view_mode)
                    elif is_directory_only:
                        # When opening a directory from command line (not restoration), ensure we stay in thumbnail mode
                        # But if it's from restoration, the restore logic above will handle it
                        directory_from_command_line = getattr(args, '_directory_from_command_line', False)
                        if directory_from_command_line:
                            def ensure_thumbnail_for_directory():
                                try:
                                    # Clear target_file to prevent browse view from opening
                                    window.target_file = None
                                    if hasattr(window, 'displayed_images') and window.displayed_images:
                                        if window.current_view_mode != 'thumbnail':
                                            window.view_manager.close_browse_view()
                                        # Ensure we're in thumbnail mode
                                        window.current_view_mode = 'thumbnail'
                                        # Just highlight the first image, don't open browse view
                                        window.highlight_index = 0
                                        window.current_index = 0
                                        window.current_image_path = window.displayed_images[0]
                                        window.highlight_image()
                                except Exception:
                                    import traceback
                                    traceback.print_exc()
                                    pass
                            QTimer.singleShot(300, ensure_thumbnail_for_directory)
                except Exception:
                    import traceback
                    traceback.print_exc()
                    pass
            
            QTimer.singleShot(100, delayed_refresh)
            # delayed_refresh()  # DGN This seems to be OK w/o the qtimer.singleShot(500, delayed_refresh)
        
        
        # Run the application
        result = app.exec()
        return result
        
    except Exception as e:
        display_entry_error(message_title="Application Error", message=f"Failed to start application:\n{str(e)}")
        print(f"Failed to start application:\n{str(e)}")
        clipboard = QApplication.clipboard()
        clipboard.setText(f"Failed to start application:\n{str(e)}")
        traceback.print_exc()
        return 1

def open_directory_dialog(args):
    app = QApplication.instance()
    if app is None:
        app = QApplication([])

    dialog = QFileDialog()
    dialog.setFileMode(QFileDialog.Directory)
    dialog.setOption(QFileDialog.ShowDirsOnly, True)
    dialog.setOption(QFileDialog.DontUseNativeDialog, False)
    dialog.setViewMode(QFileDialog.Detail)
    dialog.setDirectory(os.path.expanduser("~"))
    if dialog.exec():
        selected_dirs = dialog.selectedFiles()
        if selected_dirs:
            args.paths = selected_dirs
            return selected_dirs
        else:
            print("No directory selected, exiting.")
            sys.exit(0)
    else:
        print("Dialog canceled, exiting.")
        sys.exit(0)
def open_file_dialog(args):
    app = QApplication.instance()
    if app is None:
        app = QApplication([])

    # Supported image extensions (from config)
    image_exts = get_image_extensions()
    # Create filter string for QFileDialog
    image_filter = "Image Files (" + " ".join(f"*{ext}" for ext in sorted(image_exts)) + ")"

    # Use QFileDialog to get files or directories
    dialog = QFileDialog()
    dialog.setFileMode(QFileDialog.ExistingFiles)  # Allow selecting files
    dialog.setOption(QFileDialog.ShowDirsOnly, False)  # Allow files and dirs
    dialog.setViewMode(QFileDialog.Detail)
    dialog.setDirectory(os.path.expanduser("~"))
    dialog.setNameFilter(image_filter)

    # Try to use the native dialog and filter out non-image files
    # On macOS and Windows, the native dialog will hide non-matching files, but always show directories.
    # On Linux, this may depend on the desktop environment.
    dialog.setOption(QFileDialog.DontUseNativeDialog, False)

    # Use exec() instead of exec_() to avoid DeprecationWarning
    logging.debug(f"Opening file dialog for image selection. {image_exts}")
    if dialog.exec():
        selected = dialog.selectedFiles()
        logging.debug(f"User selected: {selected}")
        valid = []
        for p in selected:
            if os.path.isdir(p):
                logging.debug(f"Selected directory: {p}")
                valid.append(p)
            elif os.path.isfile(p):
                from utils import validate_image_file
                logging.debug(f"Selected file: {p}")
                if validate_image_file(p):
                    logging.debug(f"File {p} is a valid image file.")
                    valid.append(p)
                else:
                    logging.debug(f"File {p} is not a valid image file.")
            else:
                logging.debug(f"Selected path is neither file nor directory: {p}")
        if valid:
            logging.debug(f"Valid selections: {valid}")
            args.paths = valid
            return valid
        else:
            logging.warning("No valid image file or directory selected, exiting.")
            print("No valid image file or directory selected, exiting.")
            sys.exit(0)
    else:
        print("Dialog canceled, exiting.")
        sys.exit(0)
        
if __name__ == "__main__":
    # Support for multiprocessing in PyInstaller bundles
    # This must be called before creating any multiprocessing.Process objects
    multiprocessing.freeze_support()
    
    # CRITICAL: Set start method to 'spawn' on macOS to avoid CoreFoundation fork crashes
    # PyTorch/MPS and CoreFoundation APIs are NOT fork-safe
    # This must be set before any Process objects are created
    try:
        # Try to set start method to 'spawn' (required for PyTorch/MPS compatibility)
        multiprocessing.set_start_method('spawn', force=True)
    except RuntimeError:
        # Start method already set, or spawn not available (shouldn't happen on macOS)
        pass
    
    sys.exit(main()) 