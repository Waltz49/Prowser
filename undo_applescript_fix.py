#!/usr/bin/env python3
"""
AppleScript-based undo fix for Prowser.app permission issues
This provides an alternative implementation of file restoration that uses
AppleScript to bypass potential permission restrictions in the packaged app.
"""

import os
import subprocess
import logging

from macos_process import run_osascript
from typing import Optional, Dict, Any
import shutil

# Set up logging
logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)

class AppleScriptUndoManager:
    """AppleScript-based undo manager for file operations"""
    
    def __init__(self):
        self.is_available = True
        if not self.is_available:
            logger.warning("AppleScript undo manager only available on macOS")
    
    def _generate_unique_filename(self, original_path):
        """Generate a unique filename to avoid overwriting existing files"""
        directory = os.path.dirname(original_path)
        filename = os.path.basename(original_path)
        name, ext = os.path.splitext(filename)
        
        # Check if original filename is available
        if not os.path.exists(original_path):
            return original_path
        
        # Try with "-restored" suffix
        restored_name = f"{name}-restored{ext}"
        restored_path = os.path.join(directory, restored_name)
        
        if not os.path.exists(restored_path):
            return restored_path
        
        # Try with sequential numbers
        counter = 1
        while True:
            numbered_name = f"{name}-restored-{counter}{ext}"
            numbered_path = os.path.join(directory, numbered_name)
            if not os.path.exists(numbered_path):
                return numbered_path
            counter += 1
    
    def restore_file_from_trash(self, original_path: str, original_position: Optional[int] = None) -> bool:
        """
        Restore a file from trash using AppleScript
        
        Args:
            original_path: The original file path before deletion
            original_position: Optional position in the image list
            
        Returns:
            bool: True if successful, False otherwise
        """
        if not self.is_available:
            logger.error("AppleScript not available")
            return False
        
        logger.debug(f"AppleScript undo: Starting restoration of {original_path}")
        logger.debug(f"AppleScript undo: Original position: {original_position}")
        
        try:
            # Generate unique filename to avoid overwriting existing files
            unique_path = self._generate_unique_filename(original_path)
            filename = os.path.basename(unique_path)
            directory = os.path.dirname(unique_path)
            
            logger.debug(f"AppleScript undo: Original path: {original_path}")
            logger.debug(f"AppleScript undo: Unique path: {unique_path}")
            logger.debug(f"AppleScript undo: Filename: {filename}")
            logger.debug(f"AppleScript undo: Directory: {directory}")
            
            # Check if original directory exists
            if not os.path.exists(directory):
                logger.error(f"AppleScript undo: Original directory does not exist: {directory}")
                return False
            
            # Check directory permissions
            try:
                dir_readable = os.access(directory, os.R_OK)
                dir_writable = os.access(directory, os.W_OK)
                logger.debug(f"AppleScript undo: Directory readable: {dir_readable}, writable: {dir_writable}")
            except Exception as e:
                logger.error(f"AppleScript undo: Error checking directory permissions: {e}")
            
            # Try AppleScript first
            success = self._try_applescript_restore(original_path, unique_path, filename, directory)
            if success:
                return True
            
            # If AppleScript fails, try system trash command as fallback
            logger.debug("AppleScript failed, trying system trash command fallback...")
            return self._try_system_trash_restore(filename, directory, original_path, unique_path)
            
        except Exception as e:
            logger.error(f"AppleScript undo: Exception while restoring {filename}: {e}")
            return False
    
    def _try_applescript_restore(self, original_path: str, unique_path: str, filename: str, directory: str) -> bool:
        """Try to restore file using AppleScript"""
        try:
            # Create simple AppleScript that just finds the file
            original_filename = os.path.basename(original_path)
            script = f'''
            tell application "Finder"
                try
                    -- Find the file in trash by name
                    set trashItems to items of trash
                    repeat with trashItem in trashItems
                        if name of trashItem is "{original_filename}" then
                            return "FOUND:" & name of trashItem
                        end if
                    end repeat
                    return "NOT_FOUND"
                on error
                    return "ERROR:Script failed"
                end try
            end tell
            '''
            
            logger.debug("AppleScript undo: Executing AppleScript...")
            logger.debug(f"AppleScript undo: Script content:\n{script}")
            
            # Execute the AppleScript with shorter timeout to prevent beachball
            result = run_osascript(script, timeout=10)
            
            logger.debug(f"AppleScript undo: Subprocess return code: {result.returncode}")
            logger.debug(f"AppleScript undo: Subprocess stdout: {result.stdout.strip()}")
            if result.stderr:
                logger.debug(f"AppleScript undo: Subprocess stderr: {result.stderr.strip()}")
            
            if result.returncode == 0:
                output = result.stdout.strip()
                logger.debug(f"AppleScript undo: Raw output: '{output}'")
                
                if output.startswith("FOUND:"):
                    # AppleScript found the file, now use system commands to restore it
                    found_filename = output[6:]  # Remove "FOUND:" prefix
                    logger.info(f"AppleScript undo: Found file in trash: {found_filename}")
                    
                    # Construct the trash path
                    trash_path = os.path.expanduser("~/.Trash")
                    trash_item_path = os.path.join(trash_path, found_filename)
                    logger.info(f"AppleScript undo: Constructed trash path: {trash_item_path}")
                    
                    # Try to restore using system commands
                    return self._restore_with_system_commands(trash_item_path, unique_path)
                        
                        
                elif output == "NOT_FOUND":
                    logger.debug(f"AppleScript undo: File {filename} not found in trash")
                    return False
                elif output.startswith("ERROR:"):
                    error_msg = output[6:]  # Remove "ERROR:" prefix
                    logger.error(f"AppleScript undo: Error restoring {filename}: {error_msg}")
                    return False
                else:
                    logger.debug(f"AppleScript undo: Unexpected output: '{output}'")
                    return False
            else:
                error_msg = result.stderr.strip()
                logger.error(f"AppleScript undo: Subprocess execution failed: {error_msg}")
                return False
                
        except subprocess.TimeoutExpired:
            logger.error(f"AppleScript undo: Timeout while restoring {filename}, trying system fallback")
            # Try system restore as fallback when AppleScript times out
            return self._try_system_trash_restore(filename, directory, original_path, unique_path)
        except Exception as e:
            logger.error(f"AppleScript undo: Exception while restoring {filename}: {e}")
            return False
    
    def _restore_with_system_commands(self, trash_item_path: str, target_path: str) -> bool:
        """Restore file using system commands with the actual trash path"""
        try:
            logger.info(f"System restore: Attempting to restore from {trash_item_path} to {target_path}")
            
            # Try using mv command with the actual trash path
            result = subprocess.run(
                ['mv', trash_item_path, target_path],
                capture_output=True,
                text=True,
                timeout=5
            )
            
            if result.returncode == 0:
                logger.info(f"System restore: Successfully restored file using mv")
                return True
            else:
                logger.error(f"System restore: mv command failed: {result.stderr}")
                return False
                
        except subprocess.TimeoutExpired:
            logger.error(f"System restore: mv command timed out")
            return False
        except Exception as e:
            logger.error(f"System restore: Exception: {e}")
            return False
    
    def _try_system_trash_restore(self, filename: str, directory: str, original_path: str, unique_path: str) -> bool:
        """Try to restore file using system trash command as fallback"""
        try:
            logger.debug(f"System trash fallback: Attempting to restore {filename}")
            logger.debug(f"System trash fallback: Original path: {original_path}")
            logger.debug(f"System trash fallback: Unique path: {unique_path}")
            
            # Try using mv command directly - this often works even with permission restrictions
            logger.debug("System trash fallback: Trying mv command...")
            
            # Construct the trash path using the original filename
            trash_path = os.path.expanduser("~/.Trash")
            original_filename = os.path.basename(original_path)
            trash_file_path = os.path.join(trash_path, original_filename)
            
            # Check if file exists in trash
            if os.path.exists(trash_file_path):
                logger.debug(f"System trash fallback: Found file in trash: {trash_file_path}")
                
                # Try to restore using mv command (mv preserves dates by default)
                try:
                    logger.debug(f"System trash fallback: Moving from {trash_file_path} to {unique_path}")
                    result = subprocess.run(
                        ['mv', trash_file_path, unique_path],
                        capture_output=True,
                        text=True,
                        timeout=5
                    )
                    
                    if result.returncode == 0:
                        logger.info(f"System trash fallback: Successfully restored {filename} using mv to {unique_path}")
                        return True
                    else:
                        logger.error(f"System trash fallback: mv command failed: {result.stderr}")
                        return False
                        
                except subprocess.TimeoutExpired:
                    logger.error(f"System trash fallback: mv command timed out")
                    return False
                except Exception as e:
                    logger.error(f"System trash fallback: mv command exception: {e}")
                    return False
            else:
                logger.debug(f"System trash fallback: File not found in trash: {trash_file_path}")
                logger.debug(f"System trash fallback: No matching file found for {filename}")
                return False
            
        except Exception as e:
            logger.error(f"System trash fallback: Exception: {e}")
            return False
    
    def test_connection(self) -> bool:
        """Test if AppleScript can communicate with Finder"""
        if not self.is_available:
            logger.warning("AppleScript not available")
            return False
        
        logger.debug("AppleScript undo: Testing connection to Finder...")
        
        try:
            script = '''
            tell application "Finder"
                log "AppleScript: Testing connection to Finder"
                return "OK"
            end tell
            '''
            
            result = run_osascript(script, timeout=10)
            
            success = result.returncode == 0 and result.stdout.strip() == "OK"
            logger.debug(f"AppleScript undo: Connection test result: {success}")
            
            if not success:
                logger.debug(f"AppleScript undo: Connection test failed - return code: {result.returncode}")
                if result.stderr:
                    logger.debug(f"AppleScript undo: Connection test stderr: {result.stderr.strip()}")
            
            return success
        except Exception as e:
            logger.error(f"AppleScript undo: Exception during connection test: {e}")
            return False

def test_applescript_undo():
    """Test the AppleScript undo functionality"""
    logger.info("Testing AppleScript undo functionality...")
    
    manager = AppleScriptUndoManager()
    
    if not manager.is_available:
        logger.error("AppleScript not available on this platform")
        return
    
    # Test connection
    if manager.test_connection():
        logger.info("✓ AppleScript connection to Finder: SUCCESS")
    else:
        logger.error("✗ AppleScript connection to Finder: FAILED")
        return
    
    # Test with a dummy file (won't actually restore anything)
    logger.info("Testing with dummy file path...")
    test_path = "/tmp/test_image.jpg"
    result = manager.restore_file_from_trash(test_path)
    
    if result:
        logger.info("✓ AppleScript undo test: SUCCESS")
    else:
        logger.info("✗ AppleScript undo test: FAILED (expected for non-existent file)")

if __name__ == "__main__":
    test_applescript_undo()
