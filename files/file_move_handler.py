#!/usr/bin/env python3
"""
File Move Handler for Image Browser
Handles file move/copy operations with rename protection and overwrite dialogs
Common code used by both drag-and-drop and edit menu operations
"""

import os
import shutil
from typing import List, Optional, Tuple
from PySide6.QtCore import Qt, QEvent, QObject
from PySide6.QtWidgets import QMessageBox, QWidget, QPushButton, QCheckBox, QVBoxLayout, QDialog, QLabel, QHBoxLayout, QDialogButtonBox
from config import get_config


class ButtonKeyFilter(QObject):
    """Event filter for button keyboard navigation"""
    
    def __init__(self, message_box, buttons):
        super().__init__()
        self.message_box = message_box
        self.buttons = buttons
    
    def eventFilter(self, obj, event):
        """Filter key events on buttons to enable navigation"""
        if event.type() == QEvent.Type.KeyPress:
            key = event.key()
            
            # Handle Tab/Shift+Tab navigation
            if key == Qt.Key.Key_Tab:
                if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                    # Shift+Tab: move to previous button
                    self._move_focus(obj, -1)
                else:
                    # Tab: move to next button
                    self._move_focus(obj, 1)
                return True
            
            # Handle arrow key navigation
            if key in (Qt.Key.Key_Left, Qt.Key.Key_Right):
                if key == Qt.Key.Key_Left:
                    self._move_focus(obj, -1)
                else:
                    self._move_focus(obj, 1)
                return True
        
        return False
    
    def _move_focus(self, current_button, direction):
        """Move focus to next/previous button in the list"""
        if not self.buttons or current_button not in self.buttons:
            return
        
        try:
            current_index = self.buttons.index(current_button)
        except ValueError:
            current_index = 0
        
        # Calculate new index with wrapping
        new_index = (current_index + direction) % len(self.buttons)
        self.buttons[new_index].setFocus()


class NavigableMessageBox(QMessageBox):
    """QMessageBox with explicit keyboard navigation support"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.buttons = []
        self.key_filter = None
    
class FileMoveHandler:
    """Handles file move/copy operations with rename protection"""
    
    def __init__(self, parent_widget: Optional[QWidget] = None):
        """Initialize the file move handler
        
        Args:
            parent_widget: Parent widget for dialogs (usually main window)
        """
        self.parent_widget = parent_widget
    
    def show_overwrite_dialog(self, source_path: str, target_path: str) -> Tuple[QMessageBox.StandardButton, bool]:
        """Show overwrite confirmation dialog with Yes/No/Rename/Cancel options and Apply to all checkbox
        
        Args:
            source_path: Full path to the source file being moved/copied
            target_path: Full path to the existing file at destination (would be overwritten)
            
        Returns:
            Tuple of (QMessageBox.StandardButton indicating user's choice, apply_to_all bool)
            Button values: Yes/No/Save (for Rename)/Cancel (for Cancel)
        """
        filename = os.path.basename(source_path)
        target_directory = os.path.dirname(target_path)
        normalized_dir = os.path.normpath(target_directory)
        dir_name = os.path.basename(normalized_dir)
        if not dir_name:
            dir_name = normalized_dir if normalized_dir else target_directory
        
        message = f"A file named '{filename}' already exists in '{dir_name}'.\n\nDo you want to replace it?"
        
        # Create a custom dialog instead of modifying QMessageBox layout
        dialog = QDialog(self.parent_widget)
        dialog.setWindowTitle("File Already Exists")
        dialog.setWindowModality(Qt.WindowModality.ApplicationModal)
        dialog.setMinimumWidth(420)
        
        # Create main layout
        main_layout = QVBoxLayout(dialog)
        main_layout.setSpacing(15)
        main_layout.setContentsMargins(20, 20, 20, 20)
        
        # Image preview row: source and existing target (1 or 2 images)
        from utils import create_image_preview_row
        image_paths = [p for p in (source_path, target_path) if p and os.path.isfile(p)]
        if image_paths:
            labels = ["Source" if p == source_path else "Existing" for p in image_paths]
            preview_row, _ = create_image_preview_row(image_paths, labels=labels, size=96)
            main_layout.addLayout(preview_row)
        
        # Add message label
        message_label = QLabel(message)
        message_label.setWordWrap(True)
        main_layout.addWidget(message_label)
        
        # Add checkbox for "Apply to all"
        apply_to_all_checkbox = QCheckBox("Apply to all")
        apply_to_all_checkbox.setChecked(False)
        apply_to_all_checkbox.setToolTip("Apply this action to all files in the operation")
        # apply_to_all_checkbox.setStyleSheet("background-color: transparent;")
        main_layout.addWidget(apply_to_all_checkbox)

        
        # Add button layout
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        
        # Create buttons
        cancel_button = QPushButton("Cancel")
        no_button = QPushButton("Skip")
        yes_button = QPushButton("Replace")
        rename_button = QPushButton("Rename")
        
        # Set button focus policies
        cancel_button.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        no_button.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        yes_button.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        rename_button.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        
        # Add buttons to layout
        button_layout.addWidget(cancel_button)
        button_layout.addWidget(no_button)
        button_layout.addWidget(yes_button)
        button_layout.addWidget(rename_button)
        
        main_layout.addLayout(button_layout)
        
        # Set default button
        rename_button.setDefault(True)
        rename_button.setFocus()
        
        # Connect buttons
        result = [None]  # Use list to allow modification in nested functions
        apply_to_all_result = [False]
        
        def handle_cancel():
            result[0] = QMessageBox.StandardButton.Cancel
            apply_to_all_result[0] = apply_to_all_checkbox.isChecked()
            dialog.accept()
        
        def handle_no():
            result[0] = QMessageBox.StandardButton.No
            apply_to_all_result[0] = apply_to_all_checkbox.isChecked()
            dialog.accept()
        
        def handle_yes():
            result[0] = QMessageBox.StandardButton.Yes
            apply_to_all_result[0] = apply_to_all_checkbox.isChecked()
            dialog.accept()
        
        def handle_rename():
            result[0] = QMessageBox.StandardButton.Save
            apply_to_all_result[0] = apply_to_all_checkbox.isChecked()
            dialog.accept()
        
        cancel_button.clicked.connect(handle_cancel)
        no_button.clicked.connect(handle_no)
        yes_button.clicked.connect(handle_yes)
        rename_button.clicked.connect(handle_rename)
        
        # Set tab order
        QWidget.setTabOrder(cancel_button, no_button)
        QWidget.setTabOrder(no_button, yes_button)
        QWidget.setTabOrder(yes_button, rename_button)
        QWidget.setTabOrder(rename_button, cancel_button)
        
        # Handle Escape key to cancel
        def handle_reject():
            result[0] = QMessageBox.StandardButton.Cancel
            apply_to_all_result[0] = apply_to_all_checkbox.isChecked()
            dialog.accept()
        dialog.reject = handle_reject
        
        from utils import get_dialog_shell_stylesheet, get_button_style
        dialog.setStyleSheet(get_dialog_shell_stylesheet() + get_button_style())
        
        # Execute dialog
        dialog.exec()
        
        # Return result (default to No if dialog was closed without clicking a button)
        if result[0] is None:
            result[0] = QMessageBox.StandardButton.No
        
        return (result[0], apply_to_all_result[0])
    
    def generate_renamed_path(self, target_directory: str, original_filename: str) -> Optional[str]:
        """Generate a renamed path with configurable digit suffix (e.g., filey-00023.jpg)
        
        Args:
            target_directory: Target directory for the file
            original_filename: Original filename to rename
            
        Returns:
            New file path with increment suffix, or None if no available name found
        """
        name, ext = os.path.splitext(original_filename)
        
        # Get increment length from config
        increment_length = 5  # Default
        try:
            settings = get_config().load_settings()
            increment_length = settings.get('rename_increment_length', 5)
            # Ensure it's between 3 and 6
            increment_length = max(3, min(6, increment_length))
        except Exception:
            pass  # Use default if config fails
        
        # Calculate max number based on increment_length
        max_number = 10 ** increment_length - 1
        
        # Find the next available number
        format_spec = f"0{increment_length}d"
        for i in range(1, max_number + 1):
            new_path = f"{target_directory}/{name}-{i:{format_spec}}{ext}"
            if not os.path.exists(new_path):
                return new_path
        
        # If we couldn't find an available name, return None
        return None
    
    def resolve_target_path(self, source_path: str, target_directory: str, 
                           apply_to_all_state: Optional[dict] = None) -> Tuple[Optional[str], bool]:
        """Resolve target path for a file, handling overwrite conflicts with rename dialog
        
        Args:
            source_path: Source file path
            target_directory: Target directory
            apply_to_all_state: Optional dict to track apply_to_all state across calls.
                               Keys: 'action' (Yes/No/Save/Cancel), 'apply_to_all' (bool)
            
        Returns:
            Tuple of (resolved target path or None if cancelled/skipped, should_cancel bool)
            If should_cancel is True, the entire operation should be cancelled.
        """
        if not os.path.isfile(source_path):
            return (None, False)
        
        source_filename = source_path.split('/')[-1]
        target_path = target_directory.rstrip('/') + '/' + source_filename
        
        # Check if target file exists
        if os.path.exists(target_path):
            # Check if we have a saved "apply to all" action
            if apply_to_all_state and apply_to_all_state.get('apply_to_all', False) and 'action' in apply_to_all_state:
                saved_action = apply_to_all_state['action']
                if saved_action == QMessageBox.StandardButton.No:
                    return (None, False)
                elif saved_action == QMessageBox.StandardButton.Yes:
                    return (target_path, False)
                elif saved_action == QMessageBox.StandardButton.Save:
                    renamed_path = self.generate_renamed_path(target_directory, source_filename)
                    return (renamed_path, False)
                elif saved_action == QMessageBox.StandardButton.Cancel:
                    return (None, True)  # Cancel entire operation
            
            # Show overwrite dialog
            reply, apply_to_all = self.show_overwrite_dialog(source_path, target_path)
            
            # Save the action if "apply to all" is checked
            if apply_to_all_state is not None and apply_to_all:
                apply_to_all_state['action'] = reply
                apply_to_all_state['apply_to_all'] = True
            
            if reply == QMessageBox.StandardButton.Cancel:
                # Cancel entire operation
                return (None, True)
            elif reply == QMessageBox.StandardButton.No:
                # Skip this file
                return (None, False)
            elif reply == QMessageBox.StandardButton.Yes:
                # Overwrite - proceed with original target_path
                return (target_path, False)
            elif reply == QMessageBox.StandardButton.Save:  # Rename button
                # Generate renamed filename with increment suffix
                renamed_path = self.generate_renamed_path(target_directory, source_filename)
                return (renamed_path, False)
            else:
                # Other - skip
                return (None, False)
        
        # No conflict - use original target path
        return (target_path, False)

