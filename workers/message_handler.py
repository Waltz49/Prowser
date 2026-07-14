#!/usr/bin/env python3
"""
Message Handler for Image Browser
Handles named pipe communication for external programs controlling the image browser on macOS
"""

# Standard library imports
import errno
import json
import logging
import os
import queue
import select
import threading
import time
import traceback
from typing import Dict, Any, Optional, Callable, List

# Third-party imports
from PySide6.QtCore import QObject

# Local imports
from config import get_config

# Setup logging
config = get_config()
debug_log_path = str(config.message_debug_log)
debug_logger = logging.getLogger('ImageBrowserMessageHandler')
debug_logger.setLevel(logging.DEBUG)
debug_logger.handlers.clear()
file_handler = logging.FileHandler(debug_log_path, mode='w')
file_handler.setLevel(logging.DEBUG)
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
file_handler.setFormatter(formatter)
debug_logger.addHandler(file_handler)
# Ensure logger does NOT propagate messages to the root logger and thus the console
debug_logger.propagate = False

_shared_handler: Optional["MessageHandler"] = None
_shared_handler_lock = threading.Lock()


def get_shared_message_handler(pipe_path: str = None) -> "MessageHandler":
    """Return the process-wide MessageHandler (one named-pipe listener)."""
    global _shared_handler
    with _shared_handler_lock:
        if _shared_handler is None:
            _shared_handler = MessageHandler(pipe_path)
        return _shared_handler


class MessageHandler(QObject):
    """Handles named pipe communication for the image browser.
    Uses queue-based pipeline: listener thread puts messages in queue, main thread
    polls via QTimer. No Qt/PySide from background thread - avoids GIL deadlock.
    """

    def __init__(self, pipe_path: str = None):
        super().__init__()
        if pipe_path is None:
            # Lazy load config to allow profile directory to be set first
            pipe_path = str(config.named_pipe)
        self.pipe_path = pipe_path
        self.running = False
        self.listener_thread = None
        self.message_handlers: Dict[str, Callable] = {}
        self._message_queue: queue.Queue = queue.Queue()
        self._debug_mode = None  # Cache debug_mode to avoid loading settings on every message

        debug_logger.info(f"MessageHandler initialized with pipe: {pipe_path}")

    def drain_messages(self) -> List[Dict[str, Any]]:
        """Drain all pending messages from the queue. Call from main thread only."""
        messages = []
        while True:
            try:
                messages.append(self._message_queue.get_nowait())
            except queue.Empty:
                break
        return messages

    def invoke_handlers(self, message: Dict[str, Any]) -> None:
        """Invoke registered handlers for message type. Call from main thread only."""
        message_type = message.get('type')
        if message_type and message_type in self.message_handlers:
            try:
                self.message_handlers[message_type](message)
            except Exception as e:
                debug_logger.error(f"Error in message handler for {message_type}: {e}")
    
    def start_listening(self):
        """Start listening for messages on the named pipe"""
        if self.running:
            debug_logger.warning("Message handler is already running")
            return
        
        self.running = True
        self.listener_thread = threading.Thread(target=self._listen_loop, daemon=True)
        self.listener_thread.start()
        debug_logger.info("Started message listener thread")
    
    def stop_listening(self):
        """Stop listening for messages"""
        self.running = False
        if self.listener_thread:
            self.listener_thread.join(timeout=1.0)
        debug_logger.info("Stopped message listener")
    
    def _listen_loop(self):
        """Main listening loop for the named pipe.
        Uses non-blocking open + poll to avoid blocking on open() when no writer is connected.
        """
        POLL_TIMEOUT_MS = 500  # 0.5 second - allows checking self.running

        while self.running:
            try:
                # Create the named pipe if it doesn't exist
                if not os.path.exists(self.pipe_path):
                    os.mkfifo(self.pipe_path, mode=0o600)
                    debug_logger.info(f"Created named pipe: {self.pipe_path}")

                # Open the pipe for reading (non-blocking - does not block waiting for writer)
                pipe_fd = os.open(self.pipe_path, os.O_RDONLY | os.O_NONBLOCK)
                try:
                    debug_logger.info("Opened named pipe for reading (non-blocking)")

                    poller = select.poll()
                    poller.register(pipe_fd, select.POLLIN)

                    buffer = ""
                    while self.running:
                        events = poller.poll(POLL_TIMEOUT_MS)
                        if not events:
                            continue  # timeout - recheck self.running

                        try:
                            data = os.read(pipe_fd, 4096)
                        except BlockingIOError:
                            continue
                        except OSError as e:
                            if e.errno == errno.EAGAIN:
                                continue
                            if self.running:
                                debug_logger.error(f"Error reading from pipe: {e}")
                            break

                        if not data:
                            break  # EOF - writer closed, reopen pipe

                        buffer += data.decode('utf-8')
                        while '\n' in buffer:
                            line, buffer = buffer.split('\n', 1)
                            line = line.strip()
                            if not line:
                                continue

                            debug_logger.info(f"Received message: {line}")

                            # Log the raw message to ~/.prowser/logs/messages for debugging
                            try:
                                import datetime
                                timestamp = datetime.datetime.now().isoformat()
                                log_entry = {
                                    'timestamp': timestamp,
                                    'raw_message': line,
                                    'direction': 'raw_received'
                                }
                                with open(config.messages_log, 'a') as log_file:
                                    json.dump(log_entry, log_file)
                                    log_file.write('\n')
                                    log_file.flush()
                            except Exception as log_error:
                                debug_logger.error(f"Error logging raw message to {config.messages_log}: {log_error}")

                            # Parse the JSON message
                            try:
                                message = json.loads(line)

                                # Only print configuration in debug mode (cache check to avoid loading settings on every message)
                                if self._debug_mode is None:
                                    settings = config.load_settings()
                                    self._debug_mode = settings.get('debug_mode', False)

                                if self._debug_mode:
                                    print(f"Configuration received via pipe:\n{json.dumps(message, indent=2)}")

                                self._handle_message(message)
                            except json.JSONDecodeError as e:
                                debug_logger.error(f"Failed to parse JSON message: {e}")
                                print(f"Error parsing incoming JSON: {e}")
                                print(f"Configuration: {line}")
                                continue

                except (OSError, IOError) as e:
                    if self.running:
                        debug_logger.error(f"Error in pipe loop: {e}")
                finally:
                    try:
                        poller.unregister(pipe_fd)
                    except (KeyError, OSError):
                        pass
                    try:
                        os.close(pipe_fd)
                    except OSError:
                        pass

            except Exception as e:
                debug_logger.error(f"Error in listen loop: {e}")
                if self.running:
                    time.sleep(1.0)  # Wait before retrying
    
    def _handle_message(self, message: Dict[str, Any]):
        """Handle a received message"""
        try:
            # Validate message
            if not self._validate_message(message):
                return
            
            # Log the received message to ~/.prowser/logs/messages for debugging
            try:
                import datetime
                timestamp = datetime.datetime.now().isoformat()
                log_entry = {
                    'timestamp': timestamp,
                    'received_message': message,
                    'direction': 'received_by_handler'
                }
                with open(config.messages_log, 'a') as log_file:
                    json.dump(log_entry, log_file)
                    log_file.write('\n')
                    log_file.flush()
            except Exception as log_error:
                debug_logger.error(f"Error logging received message to {config.messages_log}: {log_error}")
            
            message_type = message.get('type')
            # Messages with 'files' or 'directory' don't need a 'type' field (new API format)
            if not message_type:
                if 'files' in message or 'directory' in message:
                    # This is a load files/directory message (new API format)
                    # No type needed - _handle_configuration will handle it via else clause
                    message_type = None
                else:
                    debug_logger.error("Message missing 'type' field and no 'files' or 'directory' field")
                    return
            
            # Put in queue for main thread to process (no Qt emit - avoids GIL deadlock)
            self._message_queue.put(message)
            debug_logger.info(f"Queued message for main thread: {message_type or 'files/directory'}")
                
        except Exception as e:
            debug_logger.error(f"Error handling message: {e}")
    
    def _validate_message(self, message: Dict[str, Any]) -> bool:
        """Validate that a message has the required fields"""
        # Special message types don't need files or directory
        message_type = message.get('type')
        if message_type in ['ping', 'quit', 'activate']:
            return True
        
        # Message must have either 'files' or 'directory'
        if 'files' not in message and 'directory' not in message:
            debug_logger.warning("Message missing 'files' or 'directory' field")
            return False
        
        # If files are specified, they must be a list
        if 'files' in message and not isinstance(message['files'], list):
            debug_logger.warning("Message 'files' field must be a list")
            return False
        
        # If directory is specified, it must be a string
        if 'directory' in message and not isinstance(message['directory'], str):
            debug_logger.warning("Message 'directory' field must be a string")
            return False
        
        return True
    
    def cleanup(self):
        """Clean up resources"""
        self.stop_listening()
        try:
            if os.path.exists(self.pipe_path):
                os.unlink(self.pipe_path)
                debug_logger.info(f"Removed named pipe: {self.pipe_path}")
        except Exception as e:
            debug_logger.error(f"Error cleaning up pipe: {e}")
    
