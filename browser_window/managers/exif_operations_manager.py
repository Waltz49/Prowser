#!/usr/bin/env python3
"""
EXIF date and UserComment operations for the main window.
"""

import os
from datetime import datetime
from typing import List, Optional

from PIL import Image
from PySide6.QtWidgets import QApplication

from browser_window.dialogs.delete_exif_dialog import DeleteExifDialog
from browser_window.dialogs.normalize_exif_steps_dialog import NormalizeExifStepsDialog
from browser_window.dialogs.normalize_exif_steps_scope_dialog import NormalizeExifStepsScopeDialog
from browser_window.dialogs.reset_date_dialog import ResetDateDialog
from browser_window.dialogs.reset_exif_dialog import ResetExifDialog
from config import get_config
from exif.exif_image_loader import get_image_dimensions_and_exif_date
from exif.exif_utils import get_exif_bytes_from_pil_raw, get_exif_dict_from_pil
from files.file_operations_manager import get_file_extension
from utils import (
    create_titled_progress_dialog,
    file_string,
    is_root_or_system_volume,
    present_auxiliary_dialog,
    raise_dialog_without_space_hop,
    show_styled_information,
    show_styled_warning,
)


class ExifOperationsManager:
    """Batch EXIF date and step-suffix operations (delegated from ImageBrowserWindow)."""

    _FIELDS_EXIF = frozenset({'exif'})
    _FIELDS_MTIME = frozenset({'mtime'})
    _FIELDS_EXIF_MTIME = frozenset({'exif', 'mtime'})

    def __init__(self, main_window):
        self.main_window = main_window

    @property
    def mw(self):
        return self.main_window

    def _after_exif_batch_success(self, modified_paths, metadata_fields=None) -> None:
        """Invalidate per-file cache (emits FILE_METADATA_CHANGED) and refresh the directory."""
        paths = [file_path for file_path in modified_paths if file_path]
        if not paths:
            return
        cache_manager = getattr(self.mw, 'cache_manager', None)
        if cache_manager:
            if len(paths) == 1:
                cache_manager.clear_cache_for_file(paths[0], metadata_fields=metadata_fields)
            else:
                cache_manager.clear_cache_for_files_batch(paths, metadata_fields=metadata_fields)
        if hasattr(self.mw, 'debounce_refresh_directory'):
            self.mw.debounce_refresh_directory()

    def reset_date_to_exif(self):
        """Reset modification dates of selected images to match their EXIF data"""
        # Check if we're in thumbnail mode and not in specific files mode
        if self.mw.current_view_mode != 'thumbnail':
            self.mw.status_notification.show_message("This feature is only available in thumbnail mode")
            return

        if getattr(self.mw, 'specific_files_active', False):
            self.mw.status_notification.show_message("This feature is not available in specific files mode")
            return

        # Get selected files
        selected_files = self.mw.selection_manager.get_selected_files()
        if not selected_files:
            self.mw.status_notification.show_message("No files selected")
            return

        # Scan selected images for EXIF data
        files_to_change = []
        for file_path in selected_files:
            if not os.path.exists(file_path):
                continue

            try:
                # Get current modification time
                current_mtime = os.path.getmtime(file_path)

                # Get EXIF date/time
                result = get_image_dimensions_and_exif_date(file_path)
                if result:
                    _, exif_timestamp = result
                    if exif_timestamp is not None:
                        # Check if dates already match (within 1 second tolerance)
                        if abs(current_mtime - exif_timestamp) > 1:
                            files_to_change.append((file_path, current_mtime, exif_timestamp))
            except Exception:
                # Skip files that can't be processed
                continue

        if not files_to_change:
            show_styled_information(self.mw, "Reset Date to EXIF", "No files need date changes (all match EXIF or have no EXIF data)")
            return

        # Show confirmation dialog with list of files
        if not ResetDateDialog.show_confirmation(files_to_change, self.mw):
            return

        # Reset dates
        success_count = 0
        error_count = 0

        for file_path, current_mtime, exif_timestamp in files_to_change:
            try:
                # Set both atime and mtime to the EXIF timestamp
                os.utime(file_path, (exif_timestamp, exif_timestamp))

                # Verify the date was set correctly
                actual_mtime = os.path.getmtime(file_path)
                if abs(actual_mtime - exif_timestamp) > 1:
                    # Date wasn't set correctly - try again
                    os.utime(file_path, (exif_timestamp, exif_timestamp))
                    actual_mtime = os.path.getmtime(file_path)
                    if abs(actual_mtime - exif_timestamp) > 1:
                        error_count += 1
                        continue

                success_count += 1
            except Exception:
                error_count += 1
                continue

        # Show result message
        if success_count > 0:
            if error_count > 0:
                self.mw.status_notification.show_message(
                    f"Reset dates for {success_count} {file_string(success_count)}, {error_count} error(s)"
                )
            else:
                self.mw.status_notification.show_message(
                    f"Successfully reset dates for {success_count} {file_string(success_count)}"
                )

            self._after_exif_batch_success(
                [file_path for file_path, _, _ in files_to_change],
                metadata_fields=self._FIELDS_MTIME,
            )
        else:
            self.mw.status_notification.show_message(f"Failed to reset dates for {error_count} {file_string(error_count)}")

    def reset_exif_to_file_date(self):
        """Reset EXIF date/time of selected images to match their file modification dates"""
        # Check if we're in thumbnail mode and not in specific files mode
        if self.mw.current_view_mode != 'thumbnail':
            self.mw.status_notification.show_message("This feature is only available in thumbnail mode")
            return

        if getattr(self.mw, 'specific_files_active', False):
            self.mw.status_notification.show_message("This feature is not available in specific files mode")
            return

        # Get selected files
        selected_files = self.mw.selection_manager.get_selected_files()
        if not selected_files:
            self.mw.status_notification.show_message("No files selected")
            return

        # Scan selected images to check which ones can be updated and which already have EXIF date/time
        files_to_update = []
        files_with_existing_exif = 0

        for file_path in selected_files:
            if not os.path.exists(file_path):
                continue

            try:
                # Get file modification time
                file_mtime = os.path.getmtime(file_path)

                # Check if file has existing EXIF date/time
                result = get_image_dimensions_and_exif_date(file_path)
                old_exif_timestamp = None
                if result:
                    _, exif_timestamp = result
                    if exif_timestamp is not None:
                        old_exif_timestamp = exif_timestamp

                        # Check if EXIF date already matches file date (within 1 second tolerance)
                        if abs(file_mtime - exif_timestamp) <= 1:
                            # Dates already match, skip this file
                            continue

                        # Only count files that will actually be updated
                        files_with_existing_exif += 1

                # Add to list of files to update with old EXIF timestamp (or None)
                files_to_update.append((file_path, file_mtime, old_exif_timestamp))
            except Exception:
                # Skip files that can't be processed
                continue

        if not files_to_update:
            show_styled_information(self.mw, "Reset EXIF to File Date", "No files need updating (all EXIF dates already match file dates or have no EXIF data)")
            return

        # Show warning dialog with Cancel as default
        if not ResetExifDialog.show_confirmation(files_to_update, files_with_existing_exif, self.mw):
            return

        # Update EXIF date/time for each file
        success_count = 0
        error_count = 0

        for file_path, file_mtime, old_exif_timestamp in files_to_update:
            temp_path = None
            try:
                # Safety check: Verify file date hasn't changed and EXIF date doesn't already match
                # (file might have been modified between scan and update)
                current_file_mtime = os.path.getmtime(file_path)
                if abs(current_file_mtime - file_mtime) > 1:
                    # File modification time changed, skip this file
                    continue

                # Double-check EXIF date doesn't already match (safety check)
                if old_exif_timestamp is not None:
                    if abs(current_file_mtime - old_exif_timestamp) <= 1:
                        # EXIF date already matches file date, skip this file
                        continue

                # Convert file modification time to EXIF date format: "YYYY:MM:DD HH:MM:SS"
                file_datetime = datetime.fromtimestamp(current_file_mtime)
                exif_date_str = file_datetime.strftime("%Y:%m:%d %H:%M:%S")

                # Determine format from file extension
                file_ext = os.path.splitext(file_path)[1].lower()
                is_webp = file_ext == '.webp'
                is_jpeg = file_ext in ['.jpg', '.jpeg']
                is_tiff = file_ext in ['.tiff', '.tif']
                is_png = file_ext == '.png'
                is_heic = file_ext in ['.heic', '.heif']

                # Try using piexif first for JPEG and WebP (formats it supports), fall back to PIL for others
                try:
                    import piexif

                    # piexif only supports JPEG and WebP
                    if is_webp or is_jpeg:
                        # Load existing EXIF data or create new structure
                        img = Image.open(file_path)
                        exif_dict = None
                        try:
                            exif_bytes = get_exif_bytes_from_pil_raw(img)
                            if exif_bytes:
                                exif_dict = piexif.load(exif_bytes)
                            else:
                                exif_dict = {"0th": {}, "Exif": {}, "GPS": {}, "1st": {}, "thumbnail": None}
                        except Exception:
                            exif_dict = {"0th": {}, "Exif": {}, "GPS": {}, "1st": {}, "thumbnail": None}

                        # Set date/time fields
                        exif_dict["Exif"][piexif.ExifIFD.DateTimeOriginal] = exif_date_str.encode("utf-8")
                        exif_dict["Exif"][piexif.ExifIFD.DateTimeDigitized] = exif_date_str.encode("utf-8")
                        exif_dict["0th"][piexif.ImageIFD.DateTime] = exif_date_str.encode("utf-8")

                        # Convert back to bytes
                        exif_bytes = piexif.dump(exif_dict)

                        # Save to temporary file first
                        temp_path = file_path + ".tmp"

                        if is_webp:
                            # For WebP files, use piexif.insert() which handles WebP metadata correctly
                            # This preserves the WebP structure and avoids corruption
                            piexif.insert(exif_bytes, file_path, temp_path)
                            img.close()
                        else:
                            # For JPEG, use PIL's save method with explicit format
                            img.save(temp_path, 'JPEG', exif=exif_bytes, quality=95)
                            img.close()
                    else:
                        # For formats piexif doesn't support (PNG, TIFF, HEIC), use PIL's method
                        raise ImportError("piexif doesn't support this format")

                except ImportError:
                    # piexif not available or format not supported by piexif, use PIL's method
                    with Image.open(file_path) as img:
                        # Get existing EXIF data
                        exif = img.getexif()
                        if exif is None:
                            # Create new EXIF object
                            exif = {}

                        # Set date/time fields using tag IDs
                        exif[306] = exif_date_str  # DateTime
                        exif[36867] = exif_date_str  # DateTimeOriginal
                        exif[36868] = exif_date_str  # DateTimeDigitized

                        # Save to temporary file first
                        temp_path = file_path + ".tmp"

                        if is_jpeg:
                            img.save(temp_path, 'JPEG', exif=exif, quality=95)
                        elif is_tiff:
                            img.save(temp_path, 'TIFF', exif=exif)
                        elif is_png:
                            # PNG supports EXIF via eXIf chunk (Pillow 6.0+)
                            img.save(temp_path, 'PNG', exif=exif)
                        elif is_webp:
                            # For WebP, explicitly specify format
                            # Note: webpmux support check removed as it causes warnings
                            # PIL will handle it if available
                            try:
                                img.save(temp_path, 'WEBP', exif=exif, quality=95, method=6)
                            except Exception:
                                # Fallback: save without EXIF if webpmux not available
                                img.save(temp_path, 'WEBP', quality=95, method=6)
                        elif is_heic:
                            # HEIC/HEIF requires pillow_heif plugin
                            try:
                                # Check if pillow_heif is registered (it should be at module level)
                                img.save(temp_path, 'HEIC', exif=exif, quality=90)
                            except Exception:
                                # If HEIC save fails, try HEIF format
                                try:
                                    img.save(temp_path, 'HEIF', exif=exif, quality=90)
                                except Exception:
                                    # If both fail, skip EXIF for HEIC
                                    img.save(temp_path, 'HEIC', quality=90)
                        else:
                            # For other formats, try to preserve format if possible
                            # Otherwise fall back to JPEG (but this may lose quality/transparency)
                            try:
                                # Try to detect format from image
                                img_format = img.format
                                if img_format:
                                    img.save(temp_path, img_format, exif=exif)
                                else:
                                    # Unknown format, fall back to JPEG
                                    img.save(temp_path, 'JPEG', exif=exif, quality=95)
                            except Exception:
                                # If format-specific save fails, try JPEG as last resort
                                img.save(temp_path, 'JPEG', exif=exif, quality=95)

                # Replace original file with updated version
                os.replace(temp_path, file_path)
                temp_path = None  # Mark as successfully replaced

                # Preserve file modification time (it might have changed during save)
                os.utime(file_path, (file_mtime, file_mtime))

                success_count += 1
            except Exception:
                error_count += 1
                # Clean up temp file if it exists
                if temp_path and os.path.exists(temp_path):
                    try:
                        os.remove(temp_path)
                    except:
                        pass
                continue

        # Show result message
        if success_count > 0:
            if error_count > 0:
                self.mw.status_notification.show_message(
                    f"Updated EXIF dates for {success_count} {file_string(success_count)}, {error_count} error(s)"
                )
            else:
                self.mw.status_notification.show_message(
                    f"Successfully updated EXIF dates for {success_count} {file_string(success_count)}"
                )

            self._after_exif_batch_success(
                [file_path for file_path, _, _ in files_to_update],
                metadata_fields=self._FIELDS_EXIF,
            )
        else:
            self.mw.status_notification.show_message(f"Failed to update EXIF dates for {error_count} {file_string(error_count)}")

    def delete_exif_date(self):
        """Delete EXIF date/time data from selected images"""
        # Check if we're in thumbnail mode and not in specific files mode
        if self.mw.current_view_mode != 'thumbnail':
            self.mw.status_notification.show_message("This feature is only available in thumbnail mode")
            return

        if getattr(self.mw, 'specific_files_active', False):
            self.mw.status_notification.show_message("This feature is not available in specific files mode")
            return

        # Get selected files
        selected_files = self.mw.selection_manager.get_selected_files()
        if not selected_files:
            self.mw.status_notification.show_message("No files selected")
            return

        # Scan selected images to check which ones have EXIF date/time data
        files_to_delete = []

        for file_path in selected_files:
            if not os.path.exists(file_path):
                continue

            try:
                # Check if file has existing EXIF date/time
                result = get_image_dimensions_and_exif_date(file_path)
                exif_timestamp = None
                if result:
                    _, exif_timestamp = result

                # Only add files that have EXIF date data
                if exif_timestamp is not None:
                    files_to_delete.append((file_path, exif_timestamp))
            except Exception:
                # Skip files that can't be processed
                continue

        if not files_to_delete:
            show_styled_information(self.mw, "Delete EXIF Date", "No files have EXIF date/time data to delete")
            return

        # Show warning dialog with Cancel as default
        if not DeleteExifDialog.show_confirmation(files_to_delete, self.mw):
            return

        # Delete EXIF date/time for each file
        success_count = 0
        error_count = 0

        for file_path, exif_timestamp in files_to_delete:
            temp_path = None
            try:
                # Preserve file modification time before processing
                file_mtime = os.path.getmtime(file_path)

                # Determine format from file extension
                file_ext = os.path.splitext(file_path)[1].lower()
                is_webp = file_ext == '.webp'
                is_jpeg = file_ext in ['.jpg', '.jpeg']
                is_tiff = file_ext in ['.tiff', '.tif']
                is_png = file_ext == '.png'
                is_heic = file_ext in ['.heic', '.heif']

                # Try using piexif first for JPEG and WebP (formats it supports), fall back to PIL for others
                try:
                    import piexif

                    # piexif only supports JPEG and WebP
                    if is_webp or is_jpeg:
                        # Load existing EXIF data
                        img = Image.open(file_path)
                        exif_dict = None
                        try:
                            exif_bytes = get_exif_bytes_from_pil_raw(img)
                            if exif_bytes:
                                exif_dict = piexif.load(exif_bytes)
                            else:
                                # No EXIF data, skip
                                img.close()
                                continue
                        except Exception:
                            # Can't load EXIF, skip
                            img.close()
                            continue

                        # Remove date/time fields
                        if "Exif" in exif_dict:
                            exif_dict["Exif"].pop(piexif.ExifIFD.DateTimeOriginal, None)
                            exif_dict["Exif"].pop(piexif.ExifIFD.DateTimeDigitized, None)
                        if "0th" in exif_dict:
                            exif_dict["0th"].pop(piexif.ImageIFD.DateTime, None)

                        # Check if there's any EXIF data left (other than empty dicts)
                        has_data = False
                        for ifd in ["0th", "Exif", "GPS", "1st"]:
                            if ifd in exif_dict and exif_dict[ifd]:
                                has_data = True
                                break

                        # Save to temporary file first
                        temp_path = file_path + ".tmp"

                        if has_data:
                            # Convert back to bytes if there's still data
                            exif_bytes = piexif.dump(exif_dict)

                            if is_webp:
                                # For WebP files, use piexif.insert() which handles WebP metadata correctly
                                piexif.insert(exif_bytes, file_path, temp_path)
                                img.close()
                            else:
                                # For JPEG, use PIL's save method with explicit format
                                img.save(temp_path, 'JPEG', exif=exif_bytes, quality=95)
                                img.close()
                        else:
                            # No EXIF data left, save without EXIF
                            if is_webp:
                                # For WebP, save without EXIF
                                img.save(temp_path, 'WEBP', quality=95, method=6)
                                img.close()
                            else:
                                # For JPEG, save without EXIF
                                img.save(temp_path, 'JPEG', quality=95)
                                img.close()
                    else:
                        # For formats piexif doesn't support (PNG, TIFF, HEIC), use PIL's method
                        raise ImportError("piexif doesn't support this format")

                except ImportError:
                    # piexif not available or format not supported by piexif, use PIL's method
                    with Image.open(file_path) as img:
                        # Save to temporary file first
                        temp_path = file_path + ".tmp"

                        # Handle PNG files specially - need to properly remove EXIF
                        if is_png:
                            # Ensure image is fully loaded
                            img.load()

                            # Get EXIF data
                            exif_dict = get_exif_dict_from_pil(img)
                            if not exif_dict:
                                # No EXIF data found, skip this file
                                continue

                            # Check if we need to preserve any non-date EXIF fields
                            date_field_ids = {306, 36867, 36868}  # DateTime, DateTimeOriginal, DateTimeDigitized
                            has_non_date_exif = any(tag_id not in date_field_ids for tag_id in exif_dict.keys())

                            # Create a completely fresh image copy to strip all metadata
                            # This is the most reliable way to remove EXIF from PNG
                            # Method: Copy pixel data to a new image - this strips ALL metadata
                            # Convert to a standard mode first to ensure pixel data copy works
                            if img.mode == 'P':
                                # Palette mode - convert to RGBA to preserve transparency
                                if 'transparency' in img.info:
                                    temp_img = img.convert('RGBA')
                                else:
                                    temp_img = img.convert('RGB')
                            else:
                                temp_img = img

                            # Now copy pixel data to completely fresh image
                            img_data = list(temp_img.getdata())
                            new_img = Image.new(temp_img.mode, temp_img.size)
                            new_img.putdata(img_data)

                            # Clean up temp image if we created one
                            if img.mode == 'P' and temp_img != img:
                                temp_img.close()

                            # Get original EXIF bytes if available (for piexif to modify while preserving non-date fields)
                            original_exif_bytes = get_exif_bytes_from_pil_raw(img)

                            # If we need to preserve non-date EXIF fields, modify EXIF bytes
                            if has_non_date_exif and original_exif_bytes:
                                try:
                                    import piexif
                                    # Parse EXIF bytes using piexif (works even for PNG)
                                    exif_dict_bytes = piexif.load(original_exif_bytes)

                                    # Remove date/time fields from piexif dict structure
                                    if "Exif" in exif_dict_bytes:
                                        exif_dict_bytes["Exif"].pop(piexif.ExifIFD.DateTimeOriginal, None)
                                        exif_dict_bytes["Exif"].pop(piexif.ExifIFD.DateTimeDigitized, None)
                                    if "0th" in exif_dict_bytes:
                                        exif_dict_bytes["0th"].pop(piexif.ImageIFD.DateTime, None)

                                    # Convert back to bytes
                                    modified_exif_bytes = piexif.dump(exif_dict_bytes)

                                    # Save with modified EXIF bytes (date fields removed, non-date fields preserved)
                                    new_img.save(temp_path, 'PNG', exif=modified_exif_bytes)
                                except Exception:
                                    # If piexif fails, fall back to saving without EXIF
                                    new_img.save(temp_path, 'PNG')
                            else:
                                # Only date fields in EXIF, or no EXIF bytes found - save without any EXIF
                                new_img.save(temp_path, 'PNG')

                            # Close the new image
                            new_img.close()
                        else:
                            # For non-PNG files, use getexif()
                            exif = img.getexif()
                            if exif is None or len(exif) == 0:
                                # No EXIF data, skip
                                continue

                            # Remove date/time fields using tag IDs
                            exif.pop(306, None)  # DateTime
                            exif.pop(36867, None)  # DateTimeOriginal
                            exif.pop(36868, None)  # DateTimeDigitized

                            # Check if there's any EXIF data left
                            if len(exif) > 0:
                                # Save with remaining EXIF data
                                if is_jpeg:
                                    img.save(temp_path, 'JPEG', exif=exif, quality=95)
                                elif is_tiff:
                                    img.save(temp_path, 'TIFF', exif=exif)
                                elif is_webp:
                                    try:
                                        img.save(temp_path, 'WEBP', exif=exif, quality=95, method=6)
                                    except Exception:
                                        # Fallback: save without EXIF if webpmux not available
                                        img.save(temp_path, 'WEBP', quality=95, method=6)
                                elif is_heic:
                                    # HEIC/HEIF requires pillow_heif plugin
                                    try:
                                        img.save(temp_path, 'HEIC', exif=exif, quality=90)
                                    except Exception:
                                        # If HEIC save fails, try HEIF format
                                        try:
                                            img.save(temp_path, 'HEIF', exif=exif, quality=90)
                                        except Exception:
                                            # If both fail, skip EXIF for HEIC
                                            img.save(temp_path, 'HEIC', quality=90)
                                else:
                                    # For other formats, try to preserve format if possible
                                    try:
                                        img_format = img.format
                                        if img_format:
                                            img.save(temp_path, img_format, exif=exif)
                                        else:
                                            img.save(temp_path, 'JPEG', exif=exif, quality=95)
                                    except Exception:
                                        img.save(temp_path, 'JPEG', exif=exif, quality=95)
                            else:
                                # No EXIF data left, save without EXIF
                                if is_jpeg:
                                    img.save(temp_path, 'JPEG', quality=95)
                                elif is_tiff:
                                    img.save(temp_path, 'TIFF')
                                elif is_webp:
                                    try:
                                        img.save(temp_path, 'WEBP', quality=95, method=6)
                                    except Exception:
                                        img.save(temp_path, 'WEBP', quality=95, method=6)
                                elif is_heic:
                                    try:
                                        img.save(temp_path, 'HEIC', quality=90)
                                    except Exception:
                                        try:
                                            img.save(temp_path, 'HEIF', quality=90)
                                        except Exception:
                                            img.save(temp_path, 'HEIC', quality=90)
                                else:
                                    try:
                                        img_format = img.format
                                        if img_format:
                                            img.save(temp_path, img_format)
                                        else:
                                            img.save(temp_path, 'JPEG', quality=95)
                                    except Exception:
                                        img.save(temp_path, 'JPEG', quality=95)

                # Replace original file with updated version
                if temp_path and os.path.exists(temp_path):
                    os.replace(temp_path, file_path)
                    temp_path = None  # Mark as successfully replaced

                    # Restore file modification time (preserved from before processing)
                    os.utime(file_path, (file_mtime, file_mtime))
                else:
                    # No temp file was created - this shouldn't happen
                    raise Exception("No temp file was created during processing")

                # Verify that EXIF date fields were actually removed
                verification_failed = False
                diagnostic_info = []

                try:
                    # Reopen the saved file and check for EXIF date fields
                    with Image.open(file_path) as verify_img:
                        verify_img.load()

                        # Check for EXIF using both methods
                        verify_exif_dict = None
                        if hasattr(verify_img, '_getexif') and verify_img._getexif():
                            verify_exif_dict = verify_img._getexif()
                        elif hasattr(verify_img, 'getexif'):
                            try:
                                verify_exif_obj = verify_img.getexif()
                                if verify_exif_obj and len(verify_exif_obj) > 0:
                                    verify_exif_dict = {}
                                    for tag_id in verify_exif_obj:
                                        verify_exif_dict[tag_id] = verify_exif_obj[tag_id]
                            except:
                                pass

                        if verify_exif_dict:
                            # Check for date fields
                            date_field_ids = {306: "DateTime", 36867: "DateTimeOriginal", 36868: "DateTimeDigitized"}
                            found_date_fields = []

                            for tag_id, field_name in date_field_ids.items():
                                if tag_id in verify_exif_dict:
                                    found_date_fields.append(f"{field_name} (tag {tag_id}): {verify_exif_dict[tag_id]}")

                            if found_date_fields:
                                verification_failed = True
                                diagnostic_info.append(f"File: {os.path.basename(file_path)}")
                                diagnostic_info.append(f"Path: {file_path}")
                                diagnostic_info.append("")
                                diagnostic_info.append("EXIF date fields still present after deletion:")
                                diagnostic_info.extend(found_date_fields)
                                diagnostic_info.append("")

                                # Add info about what EXIF fields remain
                                remaining_fields = []
                                for tag_id, value in verify_exif_dict.items():
                                    if tag_id not in date_field_ids:
                                        remaining_fields.append(f"Tag {tag_id}: {value}")

                                if remaining_fields:
                                    diagnostic_info.append(f"Other EXIF fields present ({len(remaining_fields)}):")
                                    diagnostic_info.extend(remaining_fields[:10])  # Limit to first 10
                                    if len(remaining_fields) > 10:
                                        diagnostic_info.append(f"... and {len(remaining_fields) - 10} more")

                                # Check img.info for EXIF-related keys
                                exif_info_keys = [k for k in verify_img.info.keys() if 'exif' in k.lower()]
                                if exif_info_keys:
                                    diagnostic_info.append("")
                                    diagnostic_info.append(f"EXIF-related keys in img.info: {', '.join(exif_info_keys)}")

                                # Check if file has EXIF bytes in info
                                if 'exif' in verify_img.info:
                                    exif_bytes_len = len(verify_img.info['exif']) if isinstance(verify_img.info['exif'], bytes) else 'N/A'
                                    diagnostic_info.append(f"EXIF bytes in img.info['exif']: {exif_bytes_len} bytes")

                except Exception as verify_error:
                    # Verification check failed, but file was saved
                    verification_failed = True
                    diagnostic_info.append(f"File: {os.path.basename(file_path)}")
                    diagnostic_info.append(f"Path: {file_path}")
                    diagnostic_info.append("")
                    diagnostic_info.append(f"Verification check failed with error: {str(verify_error)}")

                if verification_failed:
                    # Show diagnostic information
                    diagnostic_text = "\n".join(diagnostic_info)
                    show_styled_warning(self.mw,
                        "EXIF Deletion Verification Failed",
                        f"EXIF date deletion verification failed for:\n\n{diagnostic_text}\n\n"
                        f"The file was saved, but EXIF date fields may still be present.\n\n"
                        f"Please check the file manually to confirm.",
                    )
                    error_count += 1
                else:
                    success_count += 1
            except Exception:
                error_count += 1
                # Clean up temp file if it exists
                if temp_path and os.path.exists(temp_path):
                    try:
                        os.remove(temp_path)
                    except:
                        pass
                continue

        # Show result message
        if success_count > 0:
            if error_count > 0:
                self.mw.status_notification.show_message(
                    f"Deleted EXIF dates from {success_count} {file_string(success_count)}, {error_count} error(s)"
                )
            else:
                self.mw.status_notification.show_message(
                    f"Successfully deleted EXIF dates from {success_count} {file_string(success_count)}"
                )

            self._after_exif_batch_success(
                [file_path for file_path, _ in files_to_delete],
                metadata_fields=self._FIELDS_EXIF,
            )
        else:
            self.mw.status_notification.show_message(f"Failed to delete EXIF dates from {error_count} {file_string(error_count)}")

    def normalize_exif_steps_suffix(self):
        """Remove legacy [N] step suffix from Image Model in EXIF UserComment."""
        if self.mw.current_view_mode != 'thumbnail':
            self.mw.status_notification.show_message(
                "This feature is only available in thumbnail mode"
            )
            return

        if getattr(self.mw, 'specific_files_active', False):
            self.mw.status_notification.show_message(
                "This feature is not available in specific files mode"
            )
            return

        from PySide6.QtWidgets import QApplication

        from exif.exif_utils import (
            decode_usercomment,
            encode_usercomment,
            get_usercomment_from_path,
            restore_usercomment_to_file,
        )
        from faces.face_scan_runner import get_image_list
        from imagegen_plugins.image_gen_naming import normalize_legacy_exif_steps_suffix

        exif_comment_extensions = {'.jpg', '.jpeg', '.png', '.tiff', '.tif', '.webp'}
        selected_files = self.mw.selection_manager.get_selected_files() or []
        selected_exif_count = sum(
            1
            for file_path in selected_files
            if os.path.isfile(file_path)
            and get_file_extension(file_path) in exif_comment_extensions
        )

        current_dir = self.mw.current_directory
        if (
            not current_dir
            and getattr(self.mw, 'displayed_images', None)
            and self.mw.displayed_images
        ):
            current_dir = os.path.dirname(self.mw.displayed_images[0])
        current_dir = (
            os.path.normpath(os.path.abspath(current_dir))
            if current_dir and os.path.isdir(current_dir)
            else ""
        )

        config = get_config()
        search_depth = int(config.load_settings().get('search_depth', 4))

        scope = NormalizeExifStepsScopeDialog.ask(selected_exif_count, current_dir, search_depth, self.mw)
        if not scope:
            return

        def _normalize_exif_path(path: str) -> str:
            try:
                return os.path.normcase(os.path.normpath(os.path.abspath(path)))
            except Exception:
                return os.path.normcase(os.path.normpath(path))

        candidate_files: List[str] = []

        if scope == NormalizeExifStepsScopeDialog.SCOPE_SELECTED:
            if selected_exif_count <= 0:
                self.mw.status_notification.show_message(
                    "No selected files support EXIF user comments"
                )
                return
            for file_path in selected_files:
                if not os.path.isfile(file_path):
                    continue
                if get_file_extension(file_path) in exif_comment_extensions:
                    candidate_files.append(file_path)
        else:
            if not current_dir:
                self.mw.status_notification.show_message("No directory available")
                return
            if is_root_or_system_volume(current_dir):
                if current_dir == '/':
                    show_styled_warning(self.mw,
                        "Action Not Available",
                        "This action is not available on the root directory.",
                    )
                else:
                    show_styled_warning(self.mw,
                        "Action Not Available",
                        "This action is not available on system volumes.",
                    )
                return

            progress_dialog = create_titled_progress_dialog(self.mw,
                "Scan for Legacy EXIF Step Suffixes",
                0,
                indeterminate=True,
            )
            cancelled = False
            try:
                progress_dialog.setLabelText(
                    f"Scanning directory (depth {search_depth})..."
                )
                QApplication.processEvents()
                image_paths = get_image_list(current_dir, search_depth)
                for idx, file_path in enumerate(image_paths, start=1):
                    if progress_dialog.wasCanceled():
                        cancelled = True
                        break
                    if get_file_extension(file_path) in exif_comment_extensions:
                        candidate_files.append(file_path)
                    if idx % 100 == 0:
                        progress_dialog.setLabelText(
                            f"Scanning directory (depth {search_depth})...\n"
                            f"Images scanned: {idx} / {len(image_paths)}"
                        )
                        QApplication.processEvents()
            finally:
                progress_dialog.close()

            if cancelled:
                self.mw.status_notification.show_message("Scan cancelled", 2000)
                return

        files_to_update = []
        for file_path in candidate_files:
            try:
                raw = get_usercomment_from_path(file_path)
                if not raw:
                    continue
                text = decode_usercomment(raw)
                new_text, changed = normalize_legacy_exif_steps_suffix(text)
                if changed:
                    files_to_update.append((file_path, new_text))
            except Exception:
                continue

        if not files_to_update:
            show_styled_information(
                self,
                "Normalize EXIF Steps",
                "No files found with legacy [N] step suffix in Image Model.",
            )
            return

        if not NormalizeExifStepsDialog.show_confirmation(files_to_update, self.mw):
            return

        success_count = 0
        error_count = 0
        for file_path, new_text in files_to_update:
            try:
                if restore_usercomment_to_file(
                    file_path, encode_usercomment(new_text)
                ):
                    success_count += 1
                else:
                    error_count += 1
            except Exception:
                error_count += 1

        if success_count > 0:
            if error_count > 0:
                self.mw.status_notification.show_message(
                    f"Normalized EXIF steps in {success_count} "
                    f"{file_string(success_count)}, {error_count} error(s)"
                )
            else:
                self.mw.status_notification.show_message(
                    f"Successfully normalized EXIF steps in "
                    f"{success_count} {file_string(success_count)}"
                )
            self._after_exif_batch_success(
                [file_path for file_path, _ in files_to_update],
                metadata_fields=self._FIELDS_EXIF,
            )
        else:
            self.mw.status_notification.show_message(
                f"Failed to normalize EXIF steps in {error_count} "
                f"{file_string(error_count)}"
            )

    def edit_exif_usercomment(self):
        """Open a dialog to view and edit the EXIF UserComment for the current image."""
        image_path = None
        if self.mw.current_view_mode == 'browse':
            image_path = self.mw.get_current_image_path()
        elif self.mw.current_view_mode == 'thumbnail':
            selected_files = self.mw.selection_manager.get_selected_files()
            if selected_files and len(selected_files) == 1:
                image_path = selected_files[0]

        if not image_path or not os.path.exists(image_path):
            self.mw.status_notification.show_message("No image selected")
            return

        ext = os.path.splitext(image_path)[1].lower()
        if ext not in {'.jpg', '.jpeg', '.png', '.tiff', '.tif', '.webp'}:
            self.mw.status_notification.show_message(
                "This image format does not support EXIF user comments"
            )
            return

        from exif.exif_utils import (
            decode_usercomment,
            encode_usercomment,
            get_usercomment_from_path,
            restore_usercomment_to_file,
        )
        from browser_window.dialogs.edit_exif_usercomment_dialog import EditExifUserCommentDialog

        raw_bytes = get_usercomment_from_path(image_path)
        original_text = decode_usercomment(raw_bytes) if raw_bytes else ""

        existing = getattr(self, '_edit_exif_usercomment_dialog', None)
        if existing is not None and existing.isVisible():
            if existing.file_path == image_path:
                raise_dialog_without_space_hop(existing)
                return
            existing.close()

        dialog = EditExifUserCommentDialog(image_path, original_text, parent=self.mw)
        self._edit_exif_usercomment_dialog = dialog

        def _on_edit_exif_usercomment_finished(result: int) -> None:
            if getattr(self, '_edit_exif_usercomment_dialog', None) is dialog:
                self._edit_exif_usercomment_dialog = None
            if result != EditExifUserCommentDialog.DialogCode.Accepted:
                return
            new_text = dialog.get_text()
            if new_text == original_text:
                return
            encoded = encode_usercomment(new_text)
            success = restore_usercomment_to_file(image_path, encoded)
            if success:
                self.mw.status_notification.show_message("EXIF user comment saved")
                self._after_exif_batch_success(
                    [image_path],
                    metadata_fields=self._FIELDS_EXIF,
                )
            else:
                self.mw.status_notification.show_message("Failed to save EXIF user comment")

        dialog.finished.connect(_on_edit_exif_usercomment_finished)
        present_auxiliary_dialog(dialog)
