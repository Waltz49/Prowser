#!/usr/bin/env python3
"""
Wallpaper Manager
Handles desktop background operations for the image browser
"""

# Standard library imports
import hashlib
import logging
import os
import re
import shutil
import tempfile
import time
from typing import Optional

# Third-party imports
from PIL import Image, ImageOps
# Local imports
from exif_utils import get_exif_bytes_from_pil, format_supports_exif
from utils import show_styled_warning

# Local imports
import sys

# Config import for getting increment length
try:
    from config import get_config
except ImportError:
    # Fallback if config module is not available
    get_config = None

# AppKit imports for file operations - will be imported lazily when needed
_NSWorkspace = None
_NSUndoManager = None
_NSObject = None
_NSWorkspaceRecycleOperation = None

# macOS-specific imports
try:
    from Foundation import NSURL
    from AppKit import (
        NSWorkspaceDesktopImageScalingKey,
        NSWorkspaceDesktopImageAllowClippingKey,
        NSWorkspaceDesktopImageFillColorKey,
        NSScreen,
        NSColor
    )
    MACOS_APPS_AVAILABLE = True
except ImportError:
    MACOS_APPS_AVAILABLE = False
    NSURL = None
    NSWorkspaceDesktopImageScalingKey = None
    NSWorkspaceDesktopImageAllowClippingKey = None
    NSWorkspaceDesktopImageFillColorKey = None
    NSScreen = None
    NSColor = None

def _import_appkit_modules():
    """Lazily import AppKit modules when needed"""
    global _NSWorkspace, _NSUndoManager, _NSObject, _NSWorkspaceRecycleOperation
    
    if _NSWorkspace is None:
        try:
            from AppKit import NSWorkspace, NSUndoManager, NSObject, NSWorkspaceRecycleOperation
            _NSWorkspace = NSWorkspace
            _NSUndoManager = NSUndoManager
            _NSObject = NSObject
            _NSWorkspaceRecycleOperation = NSWorkspaceRecycleOperation
        except ImportError:
            pass
    
    # If AppKit is not available, we'll handle this gracefully


class WallpaperManager:
    """Manages desktop background operations"""
    
    def __init__(self, status_notification=None):
        """
        Initialize the wallpaper manager
        
        Args:
            status_notification: Optional status notification object for user feedback
        """
        self.status_notification = status_notification
        self.temp_dir = os.path.expanduser("~/tmp/prowser_wallpaper")
        os.makedirs(self.temp_dir, exist_ok=True)
        
        # Wallpaper undo functionality
        self.previous_wallpaper_path = None
        self.previous_wallpaper_backup_path = None
    
    def set_image_as_desktop_background(self, image_path: str, transformation: Optional[tuple] = None, fit_method: str = 'contain') -> bool:
        """
        Set the given image as the desktop background with letterboxing
        
        Args:
            image_path: Path to the image file to set as background
            transformation: Optional tuple of (rotation, h_flip, v_flip) to apply to the image
            fit_method: Fit method - 'contain', 'cover', 'width', or 'height' (default: 'contain')
            
        Returns:
            bool: True if successful, False otherwise
        """
        if not image_path or not os.path.exists(image_path):
            if self.status_notification:
                self.status_notification.show_error_message("No current image available")
            return False
        
        _import_appkit_modules()
        if _NSWorkspace is None:
            if self.status_notification:
                self.status_notification.show_error_message("Desktop background setting not available")
            return False
        
        try:
            
            # Ensure the wallpaper directory exists
            os.makedirs(self.temp_dir, exist_ok=True)
            
            # Backup the current wallpaper before setting a new one
            self.backup_current_wallpaper()
            
            # If source is already in our wallpaper directory, use it directly (no copy)
            source_dir = os.path.realpath(os.path.dirname(os.path.abspath(image_path)))
            temp_dir_real = os.path.realpath(self.temp_dir)
            if source_dir == temp_dir_real:
                letterboxed_path = os.path.abspath(image_path)
            else:
                letterboxed_path = None  # Will be set by processing below
            
            # Get screen dimensions (needed for both paths)
            main_screen = NSScreen.mainScreen()
            
            # Only process the image if source is not already in wallpaper directory
            if letterboxed_path is None:
                # We'll check for MD5 matches after processing to reuse existing files if they match
                # Load the original image and create letterboxed version
                with Image.open(image_path) as img:
                    # Capture EXIF from original (before any transformations) to copy to wallpaper
                    exif_bytes = get_exif_bytes_from_pil(img)

                    # Apply transformations if provided
                    if transformation:
                        rotation, h_flip, v_flip = transformation
                        
                        # Apply rotation (PIL rotates counter-clockwise, so negate to match Qt's clockwise)
                        if rotation != 0:
                            img = img.rotate(-rotation, expand=True, resample=Image.Resampling.BICUBIC)
                        
                        # Apply horizontal flip
                        if h_flip:
                            img = ImageOps.mirror(img)
                        
                        # Apply vertical flip
                        if v_flip:
                            img = ImageOps.flip(img)
                    
                    # Get screen dimensions
                    screen_frame = main_screen.frame()
                    screen_width = int(screen_frame.size.width)
                    screen_height = int(screen_frame.size.height)
                    
                    # Calculate scaling based on fit method
                    img_width, img_height = img.size
                    scale_x = screen_width / img_width
                    scale_y = screen_height / img_height
                    
                    # Determine scale based on fit method
                    if fit_method == 'contain':
                        # Fit within bounds - use smaller scale (no overflow)
                        scale = min(scale_x, scale_y)
                    elif fit_method == 'cover':
                        # Fill screen - use larger scale (may overflow)
                        scale = max(scale_x, scale_y)
                    elif fit_method == 'width':
                        # Match width exactly
                        scale = scale_x
                    elif fit_method == 'height':
                        # Match height exactly
                        scale = scale_y
                    else:
                        # Default to contain if unknown method
                        scale = min(scale_x, scale_y)
                    
                    # Calculate new dimensions
                    new_width = int(img_width * scale)
                    new_height = int(img_height * scale)
                    
                    # Calculate centering offsets
                    offset_x = (screen_width - new_width) // 2
                    offset_y = (screen_height - new_height) // 2
                    
                    # Create a new image with screen dimensions and black background
                    letterboxed_img = Image.new('RGB', (screen_width, screen_height), (0, 0, 0))
                    
                    # Resize the original image
                    resized_img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
                    
                    # Paste the resized image centered on the black background
                    letterboxed_img.paste(resized_img, (offset_x, offset_y))
                    
                    # Save the letterboxed image to a temporary file first (copy EXIF if present)
                    temp_letterboxed_path = os.path.join(self.temp_dir, "desktop.webp")
                    save_kwargs = {'quality': 95}
                    if exif_bytes and format_supports_exif('WEBP'):
                        save_kwargs['exif'] = exif_bytes
                    letterboxed_img.save(temp_letterboxed_path, 'WEBP', **save_kwargs)
                    
                    # Ensure the file is fully written and directory is ready
                    # This is especially important when the directory is newly created
                    time.sleep(0.1)  # Small delay to ensure file system is ready
                    
                    # Calculate MD5 of the temporary file
                    with open(temp_letterboxed_path, 'rb') as f:
                        temp_md5 = hashlib.md5(f.read()).hexdigest()
                    
                    # Get increment length from config
                    increment_length = 5  # Default
                    if get_config:
                        try:
                            settings = get_config().load_settings()
                            increment_length = settings.get('rename_increment_length', 5)
                            # Ensure it's between 3 and 6
                            increment_length = max(3, min(6, increment_length))
                        except Exception:
                            pass  # Use default if config fails
                    
                    # Check ALL files in the directory for MD5 matches
                    existing_file = None
                    existing_numbers = set()
                    try:
                        # Build regex pattern for variable length (for tracking numbered files)
                        pattern = rf'prowser_wallpaper-(\d{{{increment_length}}})\.webp'
                        
                        # First, check all files for MD5 matches
                        temp_filename = os.path.basename(temp_letterboxed_path)
                        if os.path.exists(self.temp_dir):
                            for filename in os.listdir(self.temp_dir):
                                # Skip the temp file we just created (check by filename to handle path normalization issues)
                                if filename == temp_filename:
                                    continue
                                    
                                existing_path = os.path.join(self.temp_dir, filename)
                                
                                # Skip directories
                                if not os.path.isfile(existing_path):
                                    continue
                                    
                                # Check MD5 hash of all files
                                try:
                                    with open(existing_path, 'rb') as f:
                                        existing_md5 = hashlib.md5(f.read()).hexdigest()
                                    if existing_md5 == temp_md5:
                                        existing_file = existing_path
                                        break  # Found a match, stop searching
                                except Exception as e:
                                    # If we can't read the existing file, skip it
                                    continue
                        
                        # Also collect existing numbers for numbered wallpaper files
                        if existing_file is None:  # Only need numbers if we're creating a new file
                            if os.path.exists(self.temp_dir):
                                for filename in os.listdir(self.temp_dir):
                                    if filename.startswith("prowser_wallpaper-") and filename.endswith(".webp"):
                                        existing_path = os.path.join(self.temp_dir, filename)
                                        
                                        # Extract the number from the filename using regex
                                        match = re.match(pattern, filename)
                                        if match:
                                            number_str = match.group(1)
                                            existing_numbers.add(int(number_str))
                    except Exception as e:
                        # If we can't list the directory, continue with creating a new file
                        pass
                    
                    # If we found an existing file with the same MD5, use it and cleanup temp file
                    if existing_file:
                        letterboxed_path = existing_file
                        # Remove the temporary file since we're using the existing one
                        try:
                            os.remove(temp_letterboxed_path)
                        except:
                            pass
                    else:
                        # Find the next available number
                        next_number = max(existing_numbers, default=0) + 1
                        
                        # Rename the temporary file to the numbered filename (using configurable length)
                        format_spec = f"0{increment_length}d"
                        letterboxed_path = os.path.join(self.temp_dir, f"prowser_wallpaper-{next_number:{format_spec}}.webp")
                        
                        # Ensure the temporary file exists and is readable
                        if not os.path.exists(temp_letterboxed_path):
                            return False
                        
                        # Ensure directory exists before renaming
                        os.makedirs(self.temp_dir, exist_ok=True)
                        
                        try:
                            os.rename(temp_letterboxed_path, letterboxed_path)
                        except Exception as e:
                            # If rename fails, copy and then remove
                            try:
                                shutil.copy2(temp_letterboxed_path, letterboxed_path)
                                try:
                                    os.remove(temp_letterboxed_path)
                                except Exception as remove_error:
                                    pass
                            except Exception as copy_error:
                                return False
            
            # Ensure the final file exists before setting wallpaper
            if not os.path.exists(letterboxed_path):
                if self.status_notification:
                    self.status_notification.show_error_message("Failed to create wallpaper file")
                return False
            
            # Set up workspace and options for stretch to fill (since we've already letterboxed)
            workspace = _NSWorkspace.sharedWorkspace()
            options = {
                NSWorkspaceDesktopImageScalingKey: 3,  # Stretch to fill (our image is already the right size)
                NSWorkspaceDesktopImageAllowClippingKey: 1,  # Allow clipping (not needed but safe)
                NSWorkspaceDesktopImageFillColorKey: NSColor.blackColor()
            }
            
            # Set the letterboxed file as background
            url = NSURL.fileURLWithPath_(letterboxed_path)
            success = workspace.setDesktopImageURL_forScreen_options_error_(
                url,
                main_screen,
                options,
                None
            )
            
            if success:
                filename = os.path.basename(image_path)
                if self.status_notification:
                    self.status_notification.show_message(f"Set '{filename}' as desktop background")
                return True
            else:
                if self.status_notification:
                    self.status_notification.show_error_message("Failed to set desktop background")
                return False
                
        except Exception as e:
            if self.status_notification:
                self.status_notification.show_error_message(f"Error setting desktop background: {str(e)}")
            return False
    
    def cleanup_temp_files(self):
        """Clean up temporary wallpaper files but preserve the directory"""
        try:
            if os.path.exists(self.temp_dir):
                # Only clean up temporary files, not the directory itself
                # This preserves user-created wallpaper files
                for filename in os.listdir(self.temp_dir):
                    file_path = os.path.join(self.temp_dir, filename)
                    # Only remove temporary files, not numbered wallpaper files
                    if filename.startswith('temp_') or filename.endswith('.tmp'):
                        try:
                            os.remove(file_path)
                            print(f"Cleaned up temporary file: {filename}")
                        except Exception as e:
                            print(f"Error removing temporary file {filename}: {e}")
        except Exception as e:
            print(f"Error cleaning up wallpaper temp files {self.temp_dir}: {e}")
    
    def backup_current_wallpaper(self) -> bool:
        """
        Backup the current wallpaper before setting a new one
        
        Returns:
            bool: True if backup was successful or no wallpaper to backup, False on error
        """
        try:
            _import_appkit_modules()
            if _NSWorkspace is None:
                return True  # No AppKit, assume no wallpaper to backup
            
            
            # Get the current wallpaper URL
            main_screen = NSScreen.mainScreen()
            workspace = _NSWorkspace.sharedWorkspace()
            current_url = workspace.desktopImageURLForScreen_(main_screen)
            
            if current_url is None:
                # No current wallpaper, nothing to backup
                self.previous_wallpaper_path = None
                self.previous_wallpaper_backup_path = None
                return True
            
            current_path = current_url.path()
            
            # Check if this is one of our managed wallpaper files
            if os.path.dirname(current_path) == self.temp_dir:
                # It's one of our files, just store the path
                self.previous_wallpaper_path = current_path
                self.previous_wallpaper_backup_path = None
                return True
            else:
                # It's an external file, create a backup copy
                # Ensure the wallpaper directory exists before creating backup
                os.makedirs(self.temp_dir, exist_ok=True)
                
                backup_filename = f"backup_wallpaper_{int(time.time())}.webp"
                backup_path = os.path.join(self.temp_dir, backup_filename)
                
                try:
                    # Copy the current wallpaper to our temp directory
                    shutil.copy2(current_path, backup_path)
                    self.previous_wallpaper_path = current_path
                    self.previous_wallpaper_backup_path = backup_path
                    return True
                except Exception as e:
                    print(f"Error backing up wallpaper: {e}")
                    return False
                    
        except Exception as e:
            print(f"Error in backup_current_wallpaper: {e}")
            return False
    
    def can_undo_wallpaper(self) -> bool:
        """
        Check if wallpaper undo is available
        
        Returns:
            bool: True if wallpaper can be undone
        """
        return (self.previous_wallpaper_path is not None or 
                self.previous_wallpaper_backup_path is not None)
    
    def undo_wallpaper(self) -> bool:
        """
        Restore the previous wallpaper
        
        Returns:
            bool: True if successful, False otherwise
        """
        # INSERT_YOUR_CODE
        # Check if we are in macOS Spaces (true OS fullscreen) mode and deny if so
        try:
            from AppKit import NSApplication
            app = NSApplication.sharedApplication()
            # 4 == NSApplicationPresentationFullScreen (macOS Spaces fullscreen)
            if hasattr(app, 'presentationOptions') and app.presentationOptions() & 4:
                show_styled_warning(None, "Undo Failed", "Cannot undo wallpaper while in OS fullscreen mode.")
                return False
        except Exception as e:
            print("wallpaper_manager.py: undo_wallpaper: Exception: ", e)
            pass
        try:
            _import_appkit_modules()
            if _NSWorkspace is None:
                show_styled_warning(None, "Undo Failed", "Desktop background setting not available")
                return False
            
            
            # Determine which path to use for restoration
            restore_path = None
            if self.previous_wallpaper_backup_path and os.path.exists(self.previous_wallpaper_backup_path):
                # Use our backup copy
                restore_path = self.previous_wallpaper_backup_path
            elif self.previous_wallpaper_path and os.path.exists(self.previous_wallpaper_path):
                # Use the original path
                restore_path = self.previous_wallpaper_path
            else:
                show_styled_warning(None, "Restore Error", "Previous wallpaper not found")
                return False
            
            # Set up workspace and options
            workspace = _NSWorkspace.sharedWorkspace()
            main_screen = NSScreen.mainScreen()
            options = {
                NSWorkspaceDesktopImageScalingKey: 3,  # Stretch to fill
                NSWorkspaceDesktopImageAllowClippingKey: 1,  # Allow clipping
                NSWorkspaceDesktopImageFillColorKey: NSColor.blackColor()
            }
            
            # Set the wallpaper
            url = NSURL.fileURLWithPath_(restore_path)
            success = workspace.setDesktopImageURL_forScreen_options_error_(
                url,
                main_screen,
                options,
                None
            )
            
            if success:
                if self.status_notification:
                    self.status_notification.show_message("Undo: Previous wallpaper restored")
                
                # Clean up backup file if it was used
                if (self.previous_wallpaper_backup_path and 
                    os.path.exists(self.previous_wallpaper_backup_path) and
                    self.previous_wallpaper_backup_path != restore_path):
                    try:
                        os.remove(self.previous_wallpaper_backup_path)
                    except:
                        pass
                
                # Clear undo state
                self.previous_wallpaper_path = None
                self.previous_wallpaper_backup_path = None
                return True
            else:
                show_styled_warning(None, "Restore Error", "Undo: Error restoring wallpaper")
                return False
                
        except Exception as e:
            show_styled_warning(None, "Restore Error", f"Undo: Error restoring wallpaper: {e}")
            return False 