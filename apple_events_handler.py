#!/usr/bin/env python3
"""
Apple Events Handler for macOS document-based application support
"""

import os
import subprocess
import time

# Local imports
from thumbnail_constants import get_image_extensions

# macOS-specific imports for Apple Events
try:
    from PySide6.QtGui import QClipboard
    from PySide6.QtWidgets import QApplication
except ImportError:
    QClipboard = None
    QApplication = None

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
