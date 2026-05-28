#!/usr/bin/env python3
"""
Image format conversion utility using PIL/Pillow
"""

import os
from typing import List, Optional, Tuple, Dict
from PIL import Image
from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QRadioButton,
    QButtonGroup,
    QCheckBox,
    QMessageBox,
    QApplication,
)
from PySide6.QtCore import Qt, QTimer
from config import get_config
from exif_utils import get_exif_bytes_from_pil, format_supports_exif
from thumbnail_constants import ERROR_COLOR_HEX
from utils import (
    show_styled_warning,
    show_styled_critical,
    get_file_extension,
    file_string,
    create_file_operation_progress_dialog,
)


def list_files_to_convert(files: List[str], target_format: str) -> List[str]:
    """Paths that need conversion: must exist and not already be target format."""
    target_ext = f'.{target_format.lower()}'
    return [
        fp
        for fp in files
        if os.path.exists(fp) and get_file_extension(fp) != target_ext
    ]


def count_files_to_convert(files: List[str], target_format: str) -> int:
    """Count files that need conversion (excluding files already in target format)"""
    return len(list_files_to_convert(files, target_format))


def check_name_conflicts(files: List[str], target_format: str) -> Dict[str, List[str]]:
    """Check for name conflicts when converting files to target format
    
    Returns:
        Dictionary mapping output paths to lists of input files that would conflict
        Empty dict if no conflicts
    """
    target_ext = f'.{target_format.lower()}'
    output_to_inputs: Dict[str, List[str]] = {}
    
    for file_path in files:
        if not os.path.exists(file_path):
            continue
        
        # Skip if already in target format
        ext = get_file_extension(file_path)
        if ext == target_ext:
            continue
        
        # Generate output path
        base_path = os.path.splitext(file_path)[0]
        output_path = f"{base_path}.{target_format.lower()}"
        
        # Track which input files map to this output
        if output_path not in output_to_inputs:
            output_to_inputs[output_path] = []
        output_to_inputs[output_path].append(file_path)
    
    # Filter to only conflicts (multiple inputs mapping to same output)
    conflicts = {output: inputs for output, inputs in output_to_inputs.items() if len(inputs) > 1}
    return conflicts


def check_existing_files(files: List[str], target_format: str) -> List[str]:
    """Check for existing files that would be overwritten
    
    Returns:
        List of output paths that already exist on disk
    """
    target_ext = f'.{target_format.lower()}'
    existing_files = []
    
    for file_path in files:
        if not os.path.exists(file_path):
            continue
        
        # Skip if already in target format
        ext = get_file_extension(file_path)
        if ext == target_ext:
            continue
        
        # Generate output path
        base_path = os.path.splitext(file_path)[0]
        output_path = f"{base_path}.{target_format.lower()}"
        
        # Check if output file already exists
        if os.path.exists(output_path):
            existing_files.append(output_path)
    
    return existing_files


def convert_image(input_path: str, output_path: str, delete_original: bool = False, preserve_date: bool = False) -> Tuple[bool, Optional[str]]:
    """Convert a single image using PIL/Pillow
    
    Returns:
        Tuple of (success: bool, error_message: Optional[str])
    """
    # Check directory write permissions before attempting conversion
    output_dir = os.path.dirname(output_path)
    if output_dir and not os.path.isdir(output_dir):
        return False, f"Output directory does not exist: {output_dir}"
    
    if output_dir:
        try:
            # Check if directory is writable
            if not os.access(output_dir, os.W_OK):
                return False, f"Directory is not writable: {output_dir}\n\nPermission denied. Check directory permissions (chmod)."
        except Exception as e:
            return False, f"Cannot check directory permissions: {output_dir}\n\nError: {str(e)}"
    
    # Save original timestamps if preserving date
    original_atime = None
    original_mtime = None
    if preserve_date and os.path.exists(input_path):
        stat_info = os.stat(input_path)
        original_atime = stat_info.st_atime
        original_mtime = stat_info.st_mtime
    
    try:
        from cr2_raw_loader import is_cr2_path, decode_cr2_to_pil, rawpy_available

        def _save_converted_image(img, exif_bytes: Optional[bytes]) -> Tuple[bool, Optional[str]]:
            """Apply format conversions and save. exif_bytes may be None (e.g. CR2 decoded RGB has no embedded EXIF)."""
            output_format = os.path.splitext(output_path)[1].lower()
            if output_format in ['.jpg', '.jpeg']:
                if img.mode in ('RGBA', 'LA'):
                    rgb_img = Image.new('RGB', img.size, (255, 255, 255))
                    if img.mode == 'RGBA':
                        rgb_img.paste(img, mask=img.split()[3])
                    else:
                        rgb_img.paste(img.convert('RGB'), mask=img.split()[1])
                    img = rgb_img
                elif img.mode == 'P':
                    if 'transparency' in img.info:
                        img = img.convert('RGBA')
                        rgb_img = Image.new('RGB', img.size, (255, 255, 255))
                        rgb_img.paste(img, mask=img.split()[3])
                        img = rgb_img
                    else:
                        img = img.convert('RGB')
                elif img.mode not in ('RGB', 'L'):
                    img = img.convert('RGB')

            save_kwargs = {}
            if output_format in ['.jpg', '.jpeg']:
                save_kwargs['quality'] = 95
                save_kwargs['optimize'] = True
            elif output_format == '.webp':
                save_kwargs['quality'] = 95
                save_kwargs['method'] = 6

            ext_to_pil = {'.jpg': 'JPEG', '.jpeg': 'JPEG', '.png': 'PNG', '.webp': 'WEBP'}
            save_format_pil = ext_to_pil.get(output_format, 'JPEG')
            if exif_bytes and format_supports_exif(save_format_pil):
                save_kwargs['exif'] = exif_bytes

            try:
                img.save(output_path, **save_kwargs)
            except PermissionError as e:
                return False, f"Permission denied when saving to:\n{output_path}\n\nDirectory may be read-only (chmod 500).\n\nError: {str(e)}"
            except OSError as e:
                return False, f"Failed to save converted image:\n{output_path}\n\nError: {str(e)}"
            return True, None

        if is_cr2_path(input_path):
            if not rawpy_available():
                return False, "CR2 conversion requires the rawpy package (LibRaw)."
            img = decode_cr2_to_pil(input_path, half_size=False)
            if img is None:
                return False, f"Failed to decode CR2:\n{input_path}"
            # Decoded RGB has no embedded EXIF; do not write EXIF back into CR2 in-place (out of scope).
            exif_bytes = None
            try:
                ok, err = _save_converted_image(img, exif_bytes)
                if not ok:
                    return False, err
            finally:
                img.close()
        else:
            with Image.open(input_path) as img:
                exif_bytes = get_exif_bytes_from_pil(img)
                ok, err = _save_converted_image(img, exif_bytes)
                if not ok:
                    return False, err
        
        # Verify the file was actually created
        if not os.path.exists(output_path):
            return False, f"Conversion appeared to succeed but output file was not created:\n{output_path}\n\nThis may indicate a permission or disk space issue."
        
        # Preserve timestamps if requested
        if preserve_date and os.path.exists(output_path) and original_atime is not None and original_mtime is not None:
            try:
                os.utime(output_path, (original_atime, original_mtime))
            except Exception as e:
                print(f"Warning: Could not preserve timestamps for {output_path}: {e}")
        
        # Delete original if requested (but not if it's in a Photos Library)
        if delete_original and os.path.exists(output_path):
            from utils import is_inside_photos_library
            if is_inside_photos_library(input_path):
                print(f"Warning: Cannot delete file from Photos Library: {input_path}")
                return True, None  # Conversion succeeded, just didn't delete original
            try:
                os.remove(input_path)
            except Exception as e:
                print(f"Warning: Could not delete original file {input_path}: {e}")
        
        return True, None
    except PermissionError as e:
        error_msg = f"Permission denied when converting:\n{input_path}\n\nError: {str(e)}"
        print(f"Error converting {input_path}: {e}")
        return False, error_msg
    except OSError as e:
        error_msg = f"OS error when converting:\n{input_path}\n\nError: {str(e)}"
        print(f"Error converting {input_path}: {e}")
        return False, error_msg
    except Exception as e:
        error_msg = f"Failed to convert image:\n{input_path}\n\nError: {str(e)}"
        print(f"Error converting {input_path}: {e}")
        return False, error_msg


class ConvertFormatDialog(QDialog):
    """Dialog for selecting target format and conversion options"""
    
    def __init__(self, parent, files: List[str]):
        super().__init__(parent)
        self.files = files
        self.config = get_config()
        self.selected_format = None
        self.delete_original = False
        self.preserve_date = False
        
        # Load saved settings (defaults for first time)
        settings = self.config.load_settings()
        self.saved_format = settings.get('convert_target_format', 'jpg')
        self.saved_delete_original = settings.get('convert_delete_original', False)
        self.saved_preserve_date = settings.get('convert_preserve_date', False)
        
        self.setup_ui()
    
    def setup_ui(self):
        """Setup the dialog UI"""
        self.setWindowTitle("Convert Selected Images")
        self.setModal(True)
        self.resize(400, 320)
        
        layout = QVBoxLayout(self)
        layout.setSpacing(15)
        layout.setContentsMargins(20, 20, 20, 20)
        
        # Format selection label
        format_label = QLabel("Select target format:")
        layout.addWidget(format_label)
        
        # Radio buttons for format selection (only one can be selected)
        self.format_group = QButtonGroup(self)
        formats = ['png', 'webp', 'jpg']
        
        for fmt in formats:
            radio = QRadioButton(fmt.upper())
            radio.setChecked(fmt == self.saved_format)
            self.format_group.addButton(radio)
            self.format_group.setId(radio, formats.index(fmt))
            layout.addWidget(radio)
            # Connect to update file count when format changes (only when checked)
            radio.toggled.connect(lambda checked, f=fmt: self.on_format_changed(f) if checked else None)
        
        # File count message (create before calling on_format_changed)
        self.file_count_label = QLabel()
        self.file_count_label.setWordWrap(True)
        layout.addWidget(self.file_count_label)
        
        # Conflict message label
        self.conflict_label = QLabel()
        self.conflict_label.setWordWrap(True)
        self.conflict_label.setStyleSheet(f"color: {ERROR_COLOR_HEX};")
        layout.addWidget(self.conflict_label)
        
        layout.addStretch()
        
        # Delete original checkbox
        self.delete_checkbox = QCheckBox("Delete original")
        self.delete_checkbox.setChecked(self.saved_delete_original)
        layout.addWidget(self.delete_checkbox)
        
        # Preserve date checkbox
        self.preserve_date_checkbox = QCheckBox("Preserve date")
        self.preserve_date_checkbox.setChecked(self.saved_preserve_date)
        layout.addWidget(self.preserve_date_checkbox)
        
        # Buttons
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        
        # Cancel button (left, default)
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setFocusPolicy(Qt.StrongFocus)
        self.cancel_button.setDefault(True)
        button_layout.addWidget(self.cancel_button)

        # Convert button (right)
        self.convert_button = QPushButton("Convert")
        self.convert_button.setFocusPolicy(Qt.StrongFocus)
        self.convert_button.setDefault(False)  # Explicitly not default
        button_layout.addWidget(self.convert_button)
        
        layout.addLayout(button_layout)
        
        # Apply centralized button styling
        from utils import get_button_style
        button_style = get_button_style()
        self.cancel_button.setStyleSheet(button_style)
        self.convert_button.setStyleSheet(button_style)
        
        # Connect buttons
        self.convert_button.clicked.connect(self.accept)
        self.cancel_button.clicked.connect(self.reject)
        
        # Set initial format (after all UI elements are created)
        if self.saved_format:
            self.on_format_changed(self.saved_format)
    
    def showEvent(self, event):
        """Override showEvent to ensure cancel button has focus when dialog is shown"""
        super().showEvent(event)
        # Set focus on cancel button after dialog is shown
        self.cancel_button.setFocus()
    
    def on_format_changed(self, format_name: str):
        """Handle format selection change"""
        self.saved_format = format_name
        self.update_file_count()
        self.check_conflicts()
    
    def update_file_count(self):
        """Update the file count message"""
        if not self.saved_format:
            return
        
        count = count_files_to_convert(self.files, self.saved_format)
        if count == 0:
            self.file_count_label.setText(f"All selected files are already in {self.saved_format.upper()} format.")
        elif count == 1:
            self.file_count_label.setText(f"1 file will be converted to {self.saved_format.upper()} format.")
        else:
            self.file_count_label.setText(f"{count} files will be converted to {self.saved_format.upper()} format.")
    
    def check_conflicts(self):
        """Check for name conflicts and existing files, update UI accordingly"""
        if not self.saved_format:
            self.conflict_label.setText("")
            self.convert_button.setEnabled(True)
            return
        
        # Check for name conflicts between selected files
        conflicts = check_name_conflicts(self.files, self.saved_format)
        
        # Check for existing files that would be overwritten
        existing_files = check_existing_files(self.files, self.saved_format)
        
        conflict_messages = []
        
        if conflicts:
            # Build conflict message
            conflict_lines = []
            for output_path, input_files in conflicts.items():
                output_name = os.path.basename(output_path)
                input_names = [os.path.basename(f) for f in input_files]
                conflict_lines.append(f"{output_name}: {', '.join(input_names)}")
            
            conflict_text = "Name conflicts detected:\n" + "\n".join(conflict_lines[:3])
            if len(conflicts) > 3:
                conflict_text += f"\n... and {len(conflicts) - 3} more conflict(s)"
            conflict_messages.append(conflict_text)
        
        if existing_files:
            # Build existing files message
            existing_names = [os.path.basename(f) for f in existing_files]
            existing_text = "Files already exist:\n" + "\n".join(existing_names[:3])
            if len(existing_files) > 3:
                existing_text += f"\n... and {len(existing_files) - 3} more {file_string(len(existing_files) - 3)}"
            conflict_messages.append(existing_text)
        
        if conflict_messages:
            # Combine messages
            combined_message = "\n\n".join(conflict_messages)
            self.conflict_label.setText(combined_message)
            self.convert_button.setEnabled(False)
        else:
            self.conflict_label.setText("")
            self.convert_button.setEnabled(True)
    
    def get_selected_format(self) -> Optional[str]:
        """Get the selected format"""
        checked_button = self.format_group.checkedButton()
        if checked_button:
            formats = ['png', 'webp', 'jpg']
            return formats[self.format_group.id(checked_button)]
        return None
    
    def get_delete_original(self) -> bool:
        """Get whether to delete original files"""
        return self.delete_checkbox.isChecked()
    
    def get_preserve_date(self) -> bool:
        """Get whether to preserve file dates"""
        return self.preserve_date_checkbox.isChecked()
    
    def accept(self):
        """Handle accept (Convert button)"""
        self.selected_format = self.get_selected_format()
        self.delete_original = self.get_delete_original()
        self.preserve_date = self.get_preserve_date()
        
        if not self.selected_format:
            show_styled_warning(self, "No Format Selected", "Please select a target format.")
            return
        
        # Check for conflicts and existing files one more time before accepting
        conflicts = check_name_conflicts(self.files, self.selected_format)
        existing_files = check_existing_files(self.files, self.selected_format)
        
        if conflicts or existing_files:
            messages = []
            if conflicts:
                messages.append("Multiple files would create the same output filename.")
            if existing_files:
                messages.append("Some output files already exist and would be overwritten.")
            
            show_styled_warning(
                self,
                "Cannot Convert",
                "Cannot convert:\n\n" + "\n".join(messages) + "\n\nPlease resolve these issues and try again."
            )
            return
        
        # Save all settings to config
        settings = self.config.load_settings()
        settings['convert_target_format'] = self.selected_format
        settings['convert_delete_original'] = self.delete_original
        settings['convert_preserve_date'] = self.preserve_date
        self.config.save_settings(settings)
        
        super().accept()


def _apply_path_remap_to_selection(main_window, path_map: Dict[str, str]) -> Optional[str]:
    """Update active image and multi-selection after paths change (e.g. format conversion).

    Thumbnail selection uses full paths in selected_files; after convert the extension
    changes so old paths must be replaced with new output paths.

    Returns the new active path when the current image was remapped, else None.
    """
    if not path_map:
        return None

    preferred_path = None

    if hasattr(main_window, 'selected_files') and main_window.selected_files:
        main_window.selected_files = {
            path_map.get(path, path) for path in main_window.selected_files
        }

    current_path = None
    if hasattr(main_window, 'get_current_image_path'):
        current_path = main_window.get_current_image_path()
    else:
        current_path = getattr(main_window, 'current_image_path', None)

    if current_path and current_path in path_map:
        preferred_path = path_map[current_path]
        if os.path.exists(preferred_path):
            if hasattr(main_window, 'set_current_image_by_path'):
                main_window.set_current_image_by_path(preferred_path, fallback_index=0)
            else:
                main_window.current_image_path = preferred_path

    return preferred_path


def convert_selected_images(main_window, files: List[str]) -> bool:
    """Convert selected images to a different format
    
    Args:
        main_window: The main window instance
        files: List of file paths to convert
        
    Returns:
        True if conversion was successful, False otherwise
    """
    if not files:
        return False
    
    # Show conversion dialog
    dialog = ConvertFormatDialog(main_window, files)
    if dialog.exec() != QDialog.Accepted:
        return False
    
    target_format = dialog.selected_format
    delete_original = dialog.delete_original
    preserve_date = dialog.preserve_date
    
    if not target_format:
        return False
    
    # Check for conflicts and existing files before proceeding (safety check)
    conflicts = check_name_conflicts(files, target_format)
    existing_files = check_existing_files(files, target_format)
    
    if conflicts or existing_files:
        messages = []
        if conflicts:
            messages.append("Multiple files would create the same output filename.")
        if existing_files:
            messages.append("Some output files already exist and would be overwritten.")
        
        show_styled_warning(
            main_window,
            "Cannot Convert",
            "Cannot convert:\n\n" + "\n".join(messages) + "\n\nPlease resolve these issues and try again."
        )
        return False
    
    # Perform conversions (only paths that actually need conversion)
    work_files = list_files_to_convert(files, target_format)
    total_work = len(work_files)
    progress_dialog = None
    if total_work > 5:
        progress_dialog = create_file_operation_progress_dialog(
            main_window, "Converting Images", total_work
        )

    converted_count = 0
    failed_count = 0
    error_messages = []  # Collect error messages for display
    convert_map: Dict[str, str] = {}

    for idx, file_path in enumerate(work_files):
        if progress_dialog:
            progress_dialog.setLabelText(
                f"Converting {idx + 1} of {total_work}"
            )
            progress_dialog.setValue(idx)
            QApplication.processEvents()
        try:
            # Generate output path (same directory, different extension)
            base_path = os.path.splitext(file_path)[0]
            output_path = f"{base_path}.{target_format.lower()}"

            # Skip if output file already exists (shouldn't happen due to checks, but safety measure)
            if os.path.exists(output_path):
                failed_count += 1
                error_messages.append(
                    f"Output file already exists: {os.path.basename(output_path)}"
                )
                continue

            # Convert the image
            success, error_msg = convert_image(
                file_path, output_path, delete_original, preserve_date
            )
            if success:
                converted_count += 1
                convert_map[file_path] = output_path
            else:
                failed_count += 1
                if error_msg:
                    error_messages.append(f"{os.path.basename(file_path)}: {error_msg}")
                else:
                    error_messages.append(
                        f"Failed to convert: {os.path.basename(file_path)}"
                    )
        finally:
            if progress_dialog:
                progress_dialog.setValue(idx + 1)
                QApplication.processEvents()

    if progress_dialog:
        progress_dialog.setValue(total_work)
        progress_dialog.close()

    # Show error messages if any conversions failed
    if error_messages:
        # Limit the number of errors shown to avoid overwhelming the user
        max_errors_to_show = 10
        if len(error_messages) > max_errors_to_show:
            error_text = "\n\n".join(error_messages[:max_errors_to_show])
            error_text += f"\n\n... and {len(error_messages) - max_errors_to_show} more error(s)"
        else:
            error_text = "\n\n".join(error_messages)
        
        show_styled_critical(
            main_window,
            "Conversion Errors",
            f"Failed to convert {failed_count} {file_string(failed_count)}:\n\n{error_text}"
        )
    
    # Show status message
    if converted_count > 0:
        if failed_count > 0:
            main_window.status_notification.show_message(
                f"Converted {converted_count} {file_string(converted_count)}, {failed_count} failed"
            )
        else:
            main_window.status_notification.show_message(
                f"Converted {converted_count} {file_string(converted_count)} to {target_format.upper()}"
            )
    else:
        main_window.status_notification.show_message("No files converted")

    preferred_path = None
    if convert_map:
        preferred_path = _apply_path_remap_to_selection(main_window, convert_map)

    # Refresh thumbnail view - use force=True to ensure thumbnails are refreshed after conversion
    # Defer slightly to avoid blocking, but don't use debounce which schedules another refresh later
    if hasattr(main_window, 'refresh_directory'):
        def deferred_refresh():
            try:
                main_window.refresh_directory(force=True)
                if convert_map:
                    target_directory = os.path.dirname(next(iter(convert_map.values())))
                    fom = getattr(main_window, 'file_operations_manager', None)
                    active_path = preferred_path
                    if not active_path and hasattr(main_window, 'get_current_image_path'):
                        active_path = main_window.get_current_image_path()
                    if fom and hasattr(fom, '_highlight_first_non_locked_after_rename'):
                        fom._highlight_first_non_locked_after_rename(
                            main_window,
                            target_directory,
                            convert_map,
                            preferred_path=active_path,
                        )
                    if hasattr(main_window, '_emit_selection_changed'):
                        main_window._emit_selection_changed()
                    if hasattr(main_window, 'highlight_image'):
                        main_window.highlight_image()
            except Exception:
                pass  # Don't fail if refresh has issues
        QTimer.singleShot(50, deferred_refresh)

    return converted_count > 0

