#!/usr/bin/env python3
"""
Background CLIP Process Controller
Manages the lifecycle of the background CLIP extraction process and IPC communication.
"""

import json
import os
import multiprocessing
import time
import socket
import select
import traceback
from typing import Optional, List
from PySide6.QtCore import QObject, Signal, QTimer

from config import get_config
from utils import _usleep_ms
from thumbnails.thumbnail_constants import RED, RESET

class BackgroundClipController(QObject):
    """Manages background CLIP extraction process lifecycle and IPC"""
    
    process_started = Signal()
    process_stopped = Signal()
    process_error = Signal(str)  # error message
    
    def __init__(self, main_window, parent=None):
        """
        Initialize background clip controller
        
        Args:
            main_window: Reference to the main ImageBrowserWindow instance
            parent: Parent QObject
        """
        super().__init__(parent)
        self.main_window = main_window
        self.config = get_config()
        self.data_dir = self.config.data_dir
        
        # Socket paths for event-driven communication
        self.command_socket_path = self.data_dir / "background_clip_control.sock"
        self.status_socket_path = self.data_dir / "background_clip_status.sock"
        
        # Status socket server for receiving updates from worker (event-driven)
        self.status_socket_server = None
        self.current_status = {"status": "stopped", "last_update": 0.0}
        
        # Import worker module - multiprocessing will use the imported module directly
        # This avoids the issue of main.py getting involved when using subprocess
        try:
            from workers.background_clip_worker import main as worker_main
            self.worker_main = worker_main
        except ImportError:
            self.worker_main = None
        
        self.process = None
        self.enabled = False
        self.pending_priority_directory: Optional[str] = None  # Priority directory to use on next start
        
        # Cache for is_process_running when process is None - avoids expensive psutil scan on every scroll
        self._process_check_cache: Optional[tuple] = None  # (result, timestamp)
        self._PROCESS_CHECK_CACHE_TTL = 2.0  # seconds
        
        # Timer to check for status updates from worker (event-driven via socket)
        self.status_check_timer = QTimer()
        self.status_check_timer.timeout.connect(self._check_status_updates)
        self.status_check_timer.setInterval(100)  # Check every 100ms for responsiveness
        self.status_check_timer.start()
        
        # Setup status socket server
        self._setup_status_socket_server()
    
    def set_enabled(self, enabled: bool):
        """Enable or disable background processing"""
        self.enabled = enabled
        if not enabled:
            self.stop_process()
        # Don't auto-start here - let idle detector trigger it
        self._update_status_bar()
    
    def start_process(self, priority_directory: Optional[str] = None):
        """Start the background process if enabled and not already running
        
        Args:
            priority_directory: Optional directory to prioritize (processed first)
                                If None, uses pending_priority_directory if set,
                                otherwise uses current_directory from main_window
        """
        # Use pending priority directory if no explicit one provided
        if priority_directory is None:
            priority_directory = self.pending_priority_directory
            self.pending_priority_directory = None  # Clear after use
        
        # If still None, use current directory as fallback to prioritize it
        if priority_directory is None:
            priority_directory = getattr(self.main_window, 'current_directory', None)
        
        if not self.enabled:
            return False
        
        # Do not start when foreground face scan is active - foreground has priority
        try:
            from faces.face_gathering_coordinator import is_foreground_face_scan_active
            if is_foreground_face_scan_active():
                return False
        except Exception:
            pass
        
        # Get directories from Favorites and Recently Used (refresh each time)
        directories = self._get_target_directories(priority_directory=priority_directory)
        
        # If no directories found, don't start process (nothing to process)
        if not directories:
            print("WARNING: No directories available for background CLIP processing (no favorites, recent directories, or current directory)")
            return False
        
        # Check if process is running BEFORE sending command
        process_already_running = self.is_process_running()
        
        # If process is running but socket isn't working, it might be stuck - restart it
        if process_already_running and self.command_socket_path.exists():
            # Test if socket is actually accepting connections
            try:
                test_sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                test_sock.settimeout(0.1)
                test_sock.connect(str(self.command_socket_path))
                test_sock.close()
            except Exception:
                # Socket exists but not accepting connections - process might be stuck
                # Force restart by stopping the stuck process
                print(f"WARNING: Worker process exists but socket not responding. Restarting process...")
                self.stop_process()
                process_already_running = False
        
        # Send command via socket (event-driven)
        # Use "resume" if process is already running and paused, "start" if not running
        if process_already_running:
            # Process is running - send resume command to ensure it's not stuck in paused state
            self._send_control_command("resume", foreground_busy=False, directories=directories)
        else:
            # Process not running - send start command
            self._send_control_command("start", foreground_busy=False, directories=directories)
        
        if process_already_running:
            self._update_status_bar()
            return True  # Already running
        
        try:
            # Get log file path for background worker
            logs_dir = self.config.logs_dir
            logs_dir.mkdir(parents=True, exist_ok=True)  # Ensure logs directory exists
            log_file = logs_dir / "background_clip_worker.log"
            
            # Write header to log file
            with open(log_file, 'a', encoding='utf-8') as log_f:
                log_f.write(f"\n{'='*80}\n")
                log_f.write(f"Background CLIP worker process started at {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
                log_f.write(f"{'='*80}\n")
            
            # Verify worker module is available
            if self.worker_main is None:
                error_msg = "Worker module not available - failed to import background_clip_worker"
                try:
                    logs_dir = self.config.logs_dir
                    logs_dir.mkdir(parents=True, exist_ok=True)
                    error_log = logs_dir / "background_clip_errors.log"
                    with open(error_log, 'a') as f:
                        f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} ERROR: {error_msg}\n")
                except: pass
                return False
            
            # Start background worker process using multiprocessing
            # CRITICAL: Always use 'spawn' on macOS to avoid CoreFoundation fork crashes
            # PyTorch/MPS and other CoreFoundation APIs are NOT fork-safe
            # Using 'fork' causes: "The process has forked and you cannot use this CoreFoundation functionality safely"
            # This is especially critical when PyTorch/MPS is loaded (which happens when loading CLIP models)
            try:
                # Always use 'spawn' on macOS (required for PyTorch/MPS compatibility)
                # 'fork' causes CoreFoundation errors and crashes with MPS/Objective-C runtime
                # PyInstaller handles spawn correctly when freeze_support() is called in main.py
                ctx = multiprocessing.get_context('spawn')
                
                self._process_check_cache = None  # Invalidate - we're starting a process
                self.process = ctx.Process(target=self.worker_main, name='BackgroundCLIPWorker')
                self.process.daemon = False  # Don't terminate when parent exits
                self.process.start()
            except Exception:
                raise
            
            # Check if process exited immediately
            # Use _usleep_ms() instead of time.sleep() to avoid GIL acquisition and UI blocking
            # _usleep_ms() uses ctypes usleep() which is GIL-free and safe to use in Qt event loop thread
            _usleep_ms(500)  # 500ms sleep - GIL-free
            if not self.process.is_alive():
                # Process exited immediately
                exit_code = self.process.exitcode
                # Check worker logs for errors
                worker_log_error = None
                try:
                    logs_dir = self.config.logs_dir
                    worker_log = logs_dir / "background_clip_worker.log"
                    if worker_log.exists():
                        with open(worker_log, 'r') as f:
                            lines = f.readlines()
                            if lines:
                                # Get last few lines that might contain errors
                                worker_log_error = ''.join(lines[-10:])
                except Exception:
                    worker_log_error = f"Error reading worker log: {e}"
                
                error_msg = f"Background CLIP process exited immediately with code {exit_code}"
                if worker_log_error:
                    error_msg += f"\nWorker log tail:\n{worker_log_error}"
                # Write to error log file (not console - no console in bundle)
                try:
                    logs_dir = self.config.logs_dir
                    logs_dir.mkdir(parents=True, exist_ok=True)
                    error_log = logs_dir / "background_clip_errors.log"
                    with open(error_log, 'a') as f:
                        f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} ERROR: {error_msg}\n")
                except: pass
                self._process_check_cache = None
                self.process = None
                self._update_status_bar()
                return False
            
            # Write to log file (not console - no console in bundle)
            try:
                logs_dir = self.config.logs_dir
                logs_dir.mkdir(parents=True, exist_ok=True)
                info_log = logs_dir / "background_clip_errors.log"
                with open(info_log, 'a') as f:
                    f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} INFO: Background CLIP worker started (PID: {self.process.pid})\n")
                    f.write(f"  Log file: {log_file}\n")
            except: pass
            self.process_started.emit()
            
            # Send start command after process starts (via socket, event-driven)
            # Worker needs time to spawn, load Qt, and create socket - retry for up to 5 seconds
            def send_start_with_retry(attempt: int = 0):
                if not self.is_process_running():
                    return
                if self._send_control_command("start", foreground_busy=False, directories=directories):
                    self._check_status_updates()
                    return  # Success
                if attempt < 9:  # Retry up to 10 times (0-9), 500ms apart
                    next_attempt = attempt + 1
                    QTimer.singleShot(500, lambda a=next_attempt: send_start_with_retry(a))
                else:
                    self._check_status_updates()
            
            QTimer.singleShot(1500, lambda: send_start_with_retry(0))  # First attempt after 1.5s
            
            # Schedule delayed status bar update to allow worker process time to update status file
            QTimer.singleShot(500, self._update_status_bar)
            return True
        except Exception as e:
            error_msg = f"Failed to start background CLIP process: {e}"
            # Write error to log file (not console - no console in bundle)
            try:
                logs_dir = self.config.logs_dir
                logs_dir.mkdir(parents=True, exist_ok=True)
                error_log = logs_dir / "background_clip_errors.log"
                with open(error_log, 'a') as f:
                    f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} ERROR: {error_msg}\n")
                    f.write(f"Traceback: {traceback.format_exc()}\n")
            except: pass
            # Don't emit error signal that might trigger dialogs - just log it
            # self.process_error.emit(error_msg)  # Commented out to prevent dialogs
            self._update_status_bar()
            return False
    
    def _get_target_directories(self, priority_directory: Optional[str] = None) -> List[str]:
        """Get directories from Favorites and Recently Used, with optional priority directory first
        
        Args:
            priority_directory: Optional directory to prioritize (added first if valid)
        
        Returns:
            List of directories with priority directory first (if provided and valid)
        """
        directories = []
        
        # Add priority directory first if provided and valid
        if priority_directory and os.path.exists(priority_directory) and os.path.isdir(priority_directory):
            directories.append(priority_directory)
        
        settings = self.config.load_settings()
        
        # Get favorites
        favorites = settings.get('favorite_directories', [None] * 9)
        for fav in favorites:
            if fav and os.path.exists(fav) and os.path.isdir(fav):
                if fav not in directories:  # Don't add if already added as priority
                    directories.append(fav)
        
        # Get recently used
        recent = settings.get('directory_menu_history', [])
        for dir_path in recent:
            if dir_path and os.path.exists(dir_path) and os.path.isdir(dir_path):
                if dir_path not in directories:  # Don't add duplicates
                    directories.append(dir_path)
        
        return directories
    
    def restart_with_priority_directory(self, priority_directory: str):
        """Schedule restart with priority directory after idle timeout
        
        Args:
            priority_directory: Directory to prioritize (will be processed first)
        """
        if not self.enabled:
            return
        
        # Store priority directory for use when idle detector triggers restart
        self.pending_priority_directory = priority_directory
        
        # Pause current process
        self.pause_process()
        
        # Reset idle detector so it will wait for idle timeout before restarting
        if hasattr(self.main_window, 'idle_detector') and self.main_window.idle_detector:
            self.main_window.idle_detector.reset()
    
    def stop_process(self):
        """Stop the background process cleanly, even if busy"""
        # First, send stop command via socket to allow graceful shutdown
        # This is important if the process is busy processing images
        if self.is_process_running():
            try:
                self._send_control_command("stop")
            except Exception:
                pass  # Continue even if write fails
        
        # Wait for process to stop - use short timeouts for fast Cmd-Q response (avoids beachball)
        # Worker checks for stop before each image; 2s is enough for it to finish current item and exit
        if self.process:
            try:
                if self.process.is_alive():
                    # Wait for graceful shutdown (worker exits on stop command)
                    self.process.join(timeout=2.0)
                    if self.process.is_alive():
                        # Still alive - terminate immediately for responsive quit
                        try:
                            self.process.terminate()
                            self.process.join(timeout=1.0)
                            if self.process.is_alive():
                                self.process.kill()
                                self.process.join(timeout=0.5)
                        except Exception:
                            pass
            except Exception:
                pass
            finally:
                self._process_check_cache = None
                self.process = None
        
        # Also check for orphaned processes (from previous sessions)
        try:
            import psutil
            current_process = psutil.Process()
            children = current_process.children(recursive=True)
            for child in children:
                try:
                    proc_name = child.name()
                    cmdline = child.cmdline()
                    is_worker = (
                        'BackgroundCLIPWorker' in proc_name or
                        any('background_clip_worker' in str(arg).lower() for arg in (cmdline or []))
                    )
                    if is_worker:
                        try:
                            self._send_control_command("stop")
                        except Exception:
                            pass
                        try:
                            child.terminate()
                            child.wait(timeout=2.0)
                            if child.is_running():
                                child.kill()
                        except Exception:
                            pass
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
        except Exception:
            pass
        
        self.process_stopped.emit()
        self._update_status_bar()
    
    def cleanup(self):
        """Cleanup resources (stop timer, stop process, etc.)"""
        # Stop the status check timer
        if self.status_check_timer.isActive():
            self.status_check_timer.stop()
        
        # Close status socket server
        self._close_status_socket_server()
        
        # Stop the background process (must be synchronous for proper cleanup)
        self.stop_process()
        
        # Ensure process is fully terminated before returning (important for cmd-Q cleanup)
        if self.process:
            try:
                if self.process.is_alive():
                    # Force terminate if still alive
                    try:
                        self.process.terminate()
                        self.process.join(timeout=2.0)
                        if self.process.is_alive():
                            self.process.kill()
                            self.process.join(timeout=1.0)
                    except Exception:
                        pass
            except Exception:
                pass
            finally:
                self._process_check_cache = None
                self.process = None
    
    def _setup_status_socket_server(self):
        """Setup Unix domain socket server for receiving status updates from worker"""
        try:
            # Remove existing socket file if it exists
            if self.status_socket_path.exists():
                self.status_socket_path.unlink()
            
            # Create Unix domain socket server
            self.status_socket_server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            self.status_socket_server.bind(str(self.status_socket_path))
            self.status_socket_server.listen(5)  # Allow multiple pending connections
            self.status_socket_server.setblocking(False)  # Non-blocking for select()
            
            if getattr(self.main_window, 'debug_mode', False):
                print(f"Status socket server setup at: {self.status_socket_path}")
        except Exception as e:
            if getattr(self.main_window, 'debug_mode', False):
                print(f"Failed to setup status socket server: {e}")
                import traceback
                traceback.print_exc()
            self.status_socket_server = None
    
    def _close_status_socket_server(self):
        """Close status socket server"""
        if self.status_socket_server:
            try:
                self.status_socket_server.close()
            except Exception:
                pass
            self.status_socket_server = None
        
        # Remove socket file
        try:
            if self.status_socket_path.exists():
                self.status_socket_path.unlink()
        except Exception:
            pass
    
    def _check_status_updates(self):
        """Check for status updates from worker via socket (event-driven)"""
        if not self.status_socket_server:
            return
        
        try:
            # Accept all pending connections (handle multiple status updates)
            while True:
                # Check if connection is available (non-blocking)
                ready, _, _ = select.select([self.status_socket_server], [], [], 0.0)
                if not ready:
                    break
                
                # Accept connection
                try:
                    conn, _ = self.status_socket_server.accept()
                except OSError:
                    break
                
                try:
                    # Read status data
                    data_parts = []
                    conn.settimeout(0.5)
                    
                    while True:
                        chunk = conn.recv(4096)
                        if not chunk:
                            break
                        data_parts.append(chunk)
                    
                    # Parse JSON status
                    if data_parts:
                        data = b''.join(data_parts).decode('utf-8')
                        status_data = json.loads(data)
                        self.current_status = status_data
                        # Update status bar immediately (event-driven)
                        self._update_status_bar()
                except (json.JSONDecodeError, socket.timeout):
                    pass
                finally:
                    conn.close()
        except Exception:
            pass
    
    def is_process_running(self) -> bool:
        """Check if background process is running"""
        if not self.enabled:
            return False
        if self.process:
            is_running = self.process.is_alive()
            # If process has terminated, clear the reference
            if not is_running:
                self._process_check_cache = None
                self.process = None
            return is_running
        
        # If self.process is None, check cache to avoid expensive psutil scan on every scroll
        if self._process_check_cache is not None:
            cached_result, cached_time = self._process_check_cache
            if time.time() - cached_time < self._PROCESS_CHECK_CACHE_TTL:
                return cached_result
        
        # Check if worker process is actually running by checking process list
        # This handles the case where the app was restarted but worker process from previous session is still running
        try:
            import psutil
            # Look for worker process by process name (multiprocessing uses process name)
            # The process name is set to 'BackgroundCLIPWorker' when we start it
            found_process = False
            for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
                try:
                    # Check if process name matches our worker process name
                    proc_name = proc.info.get('name', '')
                    cmdline = proc.info.get('cmdline', [])
                    # Multiprocessing processes may have the module name in cmdline or process name
                    is_worker = (
                        'BackgroundCLIPWorker' in proc_name or
                        any('background_clip_worker' in str(arg).lower() for arg in (cmdline or []))
                    )
                    if is_worker:
                        found_process = True
                        # Found worker process - check if socket is actually working
                        # If socket exists but isn't accepting connections, process is stuck
                        if self.command_socket_path.exists():
                            # Test if socket is actually accepting connections
                            try:
                                test_sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                                test_sock.settimeout(0.1)
                                test_sock.connect(str(self.command_socket_path))
                                test_sock.close()
                                # Socket is working, process is fine
                                self._process_check_cache = (True, time.time())
                                return True
                            except Exception:
                                # Socket exists but not accepting connections - process is stuck
                                # Kill the stuck process
                                try:
                                    proc.kill()
                                    print(f"WARNING: Killed stuck worker process (PID {proc.info['pid']}) - socket not responding")
                                except Exception:
                                    pass
                                return False
                        else:
                            # Socket doesn't exist - process might be starting or stuck
                            # Assume it's running for now, but it will be detected as not working when start_process is called
                            return True
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
            
            # If we found a process, socket check already handled return above
            # If we didn't find a process but socket exists, it's an orphaned socket - clean it up
            if not found_process and self.command_socket_path.exists():
                # Orphaned socket - remove it
                try:
                    self.command_socket_path.unlink()
                except Exception:
                    pass
        except Exception:
            pass
        
        self._process_check_cache = (False, time.time())
        return False
    
    def pause_process(self):
        """Pause the background process"""
        if not self.enabled:
            return
        # Only try to pause if process is actually running
        if self.is_process_running():
            self._send_control_command("pause")
        # Update status bar immediately
        self._update_status_bar()
    
    def resume_process(self, priority_directory: Optional[str] = None):
        """Resume the background process
        
        Args:
            priority_directory: Optional directory to prioritize (processed first)
                                If None, uses current_directory from main_window
        """
        # Get current directory if not provided
        if priority_directory is None:
            priority_directory = getattr(self.main_window, 'current_directory', None)
        
        # Update directories list with priority directory first
        directories = self._get_target_directories(priority_directory=priority_directory)
        self._send_control_command("resume", foreground_busy=False, directories=directories)
        self._update_status_bar()
    
    def flush_and_pause_process(self):
        """Request background process to flush cache and pause"""
        self._send_control_command("flush_and_pause")
        self._update_status_bar()
    
    def wait_for_flush_and_pause(self, timeout: float = 90.0) -> bool:
        """
        Wait for background process to flush and pause
        
        Args:
            timeout: Maximum time to wait in seconds
            
        Returns:
            True if flush_and_pause completed (or worker already idle), False if timeout
        """
        start_time = time.time()
        check_interval_ms = 500  # Check every 500ms
        # flush_and_pause may fail to deliver if the command socket is not ready yet (e.g. worker
        # just restarted after "socket not responding"). Status can show "running" while the worker
        # never received the command — resend periodically until we see a paused/idle state.
        resend_interval_sec = 1.0
        last_resend_time = start_time - resend_interval_sec
        last_status_log_time = 0.0
        status_log_interval_sec = 5.0

        while time.time() - start_time < timeout:
            if not self.is_process_running():
                return True
            # Process status socket directly - we're blocking so QTimer won't run
            self._check_status_updates()
            status = self._read_status_file()
            status_str = status.get("status") if status else None
            # Success: flushed_and_paused (explicit), paused, or waiting (between cycles, already flushed)
            if status_str in ("flushed_and_paused", "paused", "waiting"):
                return True
            now = time.time()
            if now - last_resend_time >= resend_interval_sec:
                self._send_control_command("flush_and_pause")
                last_resend_time = now
            if status_str and (now - last_status_log_time >= status_log_interval_sec):
                print(f"{RED}Waiting for flush and pause... current status: {status_str}{RESET}")
                last_status_log_time = now
            # Use _usleep_ms() instead of time.sleep() to avoid GIL acquisition and UI blocking
            _usleep_ms(check_interval_ms)

        return False
    
    def is_background_active(self) -> bool:
        """
        Check if background CLIP extraction is currently active (running and not paused)
        
        Returns:
            True if background process is running and actively processing, False otherwise
        """
        if not self.enabled:
            return False
        
        is_running = self.is_process_running()
        if not is_running:
            return False
        
        # Check status file to see if process is paused or waiting
        status = self._read_status_file()
        if status:
            status_str = status.get("status", "")
            # Active states: "running"
            # Inactive states: "paused", "flushed_and_paused", "stopped", "waiting"
            result = status_str == "running"
            return result
        
        # If no status file, assume inactive
        return False
    
    def prepare_for_mass_rename(self) -> bool:
        """
        Prepare for mass rename operation:
        1. Request background process to flush and pause
        2. Wait for flush completion
        3. Import background cache files
        4. Merge background index
        5. Clear background index
        
        Returns:
            True if successful, False if timeout or error
        """
        if not self.is_process_running():
            # No background process running, nothing to prepare
            return True
        
        # Step 1: Request flush and pause
        self.flush_and_pause_process()
        
        # Step 2: Wait for flush completion
        # Increased timeout to 90 seconds to accommodate large cache flushes
        flush_timeout = 90.0
        flush_completed = self.wait_for_flush_and_pause(timeout=flush_timeout)
        
        if not flush_completed:
            print(f"WARNING: Background process did not flush and pause within {flush_timeout} seconds. "
                  f"This may happen with very large caches.")
            # CRITICAL: Even if timeout occurred, we still need to import cache files
            # The background process may have flushed some data before timeout
            # Add a small delay to let any in-progress writes complete
            import time
            time.sleep(2.0)  # Wait 2 seconds for any in-progress writes to complete
            print("Attempting to import cache files despite timeout...")
        
        # Step 3-5: Import and merge cache (handled by BackgroundCacheImporter)
        # CRITICAL: Always try to import, even if flush timed out, to avoid data loss
        imported_count = 0
        if hasattr(self.main_window, 'background_cache_importer') and self.main_window.background_cache_importer:
            try:
                imported_count = self.main_window.background_cache_importer.import_all_pending()
                if imported_count > 0:
                    print(f"Imported {imported_count} background cache files before mass rename")
            except Exception as e:
                print(f"WARNING: Error importing cache files: {e}")
                # Continue anyway - better to proceed with partial cache than fail completely
        
        # Return True if flush completed OR if we imported some cache files
        # This ensures we proceed with rename even if flush timed out but we got some data
        return flush_completed or imported_count > 0
    
    def resume_after_mass_rename(self):
        """Resume background process after mass rename completes"""
        # Get current directory to prioritize
        priority_directory = getattr(self.main_window, 'current_directory', None)
        
        if self.enabled and not self.is_process_running():
            # Process might have stopped, try to restart
            self.start_process(priority_directory=priority_directory)
        else:
            self.resume_process(priority_directory=priority_directory)
    
    def _send_control_command(self, command: str, foreground_busy: bool = False, directories: Optional[List[str]] = None, debug_mode: Optional[bool] = None) -> bool:
        """Send command to background worker via Unix domain socket (event-driven, no file fallback)
        
        Args:
            command: Command to send to background worker
            foreground_busy: Whether foreground is busy
            directories: Optional list of directories to process
            debug_mode: Optional debug mode setting (if None, reads from main_window)
            
        Returns:
            True if command was successfully sent, False otherwise
        """
        # Allow "stop" command even when disabled (needed for cleanup when turning off background extracts)
        # Skip other commands if background processing is disabled
        if not self.enabled and command != "stop":
            return False
        
        # Allow "start" command even if process isn't running yet (for initial startup)
        # For other commands, require process to be running
        if command != "start" and not self.is_process_running():
            return False  # Silently return - process not running is normal
        
        # Get debug_mode from main_window if not provided
        if debug_mode is None:
            debug_mode = getattr(self.main_window, 'debug_mode', False)
        
        control_data = {
            "command": command,
            "foreground_busy": foreground_busy,
            "directories": directories or [],
            "debug_mode": debug_mode,
            "last_update": time.time(),
            "status_socket_path": str(self.status_socket_path)  # Tell worker where to send status updates
        }
        
        # Send via socket (event-driven, no file fallback)
        if self.command_socket_path.exists() and (command == "start" or self.is_process_running()):
            try:
                sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                sock.settimeout(0.5)  # 500ms timeout
                sock.connect(str(self.command_socket_path))
                
                # Send JSON data
                data = json.dumps(control_data).encode('utf-8')
                sock.sendall(data)
                sock.close()
                return True
            except (ConnectionRefusedError, OSError, socket.timeout):
                # Socket not ready - this is normal during startup or if process is starting
                # Silently ignore - no need to spam warnings
                return False
            except Exception as e:
                # Only log unexpected errors in debug mode
                if debug_mode:
                    print(f"Error sending {command} command via socket: {e}")
                return False
        return False
    
    def _read_status_file(self) -> Optional[dict]:
        """Get current status (now from in-memory cache updated via socket)"""
        return self.current_status if self.current_status.get("last_update", 0) > 0 else None
    
    def set_foreground_busy(self, busy: bool):
        """Set foreground busy flag via socket (event-driven)"""
        if not self.is_process_running():
            return
        
        # Send pause/resume command with busy flag
        # We don't need to read current state - just send the command
        self._send_control_command("pause" if busy else "resume", foreground_busy=busy)
    
    def update_debug_mode(self):
        """Update debug_mode via socket when setting changes (event-driven)"""
        if not self.is_process_running():
            return  # No need to update if process isn't running
        
        # Send current command again with updated debug_mode
        # Get debug_mode from main_window
        debug_mode = getattr(self.main_window, 'debug_mode', False)
        # Send resume command with updated debug_mode (preserves current state)
        self._send_control_command("resume", foreground_busy=False, debug_mode=debug_mode)
    
    def _update_status_bar(self):
        """Update status bar file count section to reflect background process status"""
        if hasattr(self.main_window, 'status_bar_manager') and self.main_window.status_bar_manager:
            self.main_window.status_bar_manager._update_file_count_section(self.main_window)
