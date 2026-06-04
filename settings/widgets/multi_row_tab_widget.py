#!/usr/bin/env python3
"""Settings dialog sidebar tab widget (extracted from settings_dialog.py)."""

from PySide6.QtCore import Qt, Signal, QTimer, QEvent
from PySide6.QtWidgets import (
    QButtonGroup, QHBoxLayout, QPushButton, QSizePolicy, QVBoxLayout, QWidget,
)
import thumbnail_constants as tc

# Snapshot at import for initial layout; refresh_theme_styles() re-reads tc.* after theme changes.
TAB_BUTTON_FOCUS_BACKGROUND_COLOR_HEX = tc.TAB_BUTTON_FOCUS_BACKGROUND_COLOR_HEX
TAB_BUTTON_FOCUS_BORDER_COLOR_HEX = tc.TAB_BUTTON_FOCUS_BORDER_COLOR_HEX
DIALOG_BACKGROUND_HEX = tc.DIALOG_BACKGROUND_HEX
BORDER_DEFAULT_HEX = tc.BORDER_DEFAULT_HEX
WIDGET_BG_HOVER_HEX = tc.WIDGET_BG_HOVER_HEX
TAB_BUTTON_HOVER_BG_HEX = tc.TAB_BUTTON_HOVER_BG_HEX
BUTTON_BG_DEFAULT_HEX = tc.BUTTON_BG_DEFAULT_HEX
DIALOG_TEXT_COLOR_HEX = tc.DIALOG_TEXT_COLOR_HEX

class TabButtonContainer(QWidget):
    """Container widget for tab buttons that handles focus and keyboard navigation"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.tab_widget = parent  # Reference to parent MultiRowTabWidget


class FlowLayout(QWidget):
    """Flow layout container that arranges widgets in a single vertical column"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.widgets = []
        
        # Use vertical layout for single column
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(4)
    
    def addWidget(self, widget):
        """Add a widget to the flow layout"""
        self.widgets.append(widget)
        self._updateLayout()
    
    def _updateLayout(self):
        """Update the layout by adding widgets to a single vertical column"""
        # Clear layout (remove widgets but keep widgets in self.widgets)
        while self.main_layout.count():
            item = self.main_layout.takeAt(0)
            # Don't delete widgets, just remove from layout
        
        # Add all widgets to vertical column
        for widget in self.widgets:
            self.main_layout.addWidget(widget)
        
        # Add stretch at the end so buttons don't expand to fill space
        self.main_layout.addStretch()
    
    def updateColumns(self, available_width):
        """No-op: flow layout handles wrapping automatically"""
        pass
    
    @property
    def columns_per_row(self):
        """Return columns per row for navigation calculations (1 for vertical column)"""
        return 1


class MultiRowTabWidget(QWidget):
    """Custom tab widget that supports a vertical column of tabs on the left"""
    
    currentChanged = Signal(int)  # Signal emitted when tab changes
    # Fixed width so every sidebar tab lines up in one column (same visual width).
    SIDEBAR_BUTTON_WIDTH = 200
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.tabs = []
        self.buttons = []
        self.current_index = -1
        self.tab_icons = {}  # Dictionary to store icons for each tab index
        
        # Create button group to ensure only one button is checked at a time
        self.button_group = QButtonGroup(self)
        self.button_group.setExclusive(True)  # Only one button can be checked
        
        # Use horizontal layout: buttons on left, content on right
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # Button container with flow layout - make it focusable as a single unit
        self.button_container = TabButtonContainer(self)
        self.button_container.setFocusPolicy(Qt.StrongFocus)  # Tab-able as single unit
        self.button_container.setStyleSheet(f"""
            QWidget {{
                border: 2px solid transparent;
            }}
            QWidget:focus {{
                border: 2px solid {TAB_BUTTON_FOCUS_BORDER_COLOR_HEX};
                border-radius: 4px;
            }}
        """)
        # FlowLayout is now a widget, add it to button_container
        container_layout = QVBoxLayout(self.button_container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        self.button_layout = FlowLayout(self.button_container)
        container_layout.addWidget(self.button_layout)
        self.button_container.setFixedWidth(self.SIDEBAR_BUTTON_WIDTH + 12)
        layout.addWidget(self.button_container)
        
        # Stacked widget for content
        self.stacked_widget = QWidget()
        self.stacked_widget.setMinimumHeight(360)
        self.stacked_layout = QVBoxLayout(self.stacked_widget)
        self.stacked_layout.setContentsMargins(0, 0, 0, 0)
        self.stacked_widgets = []
        layout.addWidget(self.stacked_widget, 1)  # Give content stretch factor
        
        # Style for tabs - buttons will size to content (vertical column style)
        self.tab_style = f"""
            QPushButton {{
                background-color: {DIALOG_BACKGROUND_HEX};
                color: {DIALOG_TEXT_COLOR_HEX};
                border: 1px solid {BORDER_DEFAULT_HEX};
                border-radius: 4px;
                padding: 6px 12px;
                text-align: left;
            }}
            QPushButton:hover {{
                background-color: {TAB_BUTTON_HOVER_BG_HEX};
            }}
            QPushButton:pressed {{
                background-color: {WIDGET_BG_HOVER_HEX};
            }}
            QPushButton:checked {{
                background-color: {BUTTON_BG_DEFAULT_HEX};
                border-left: 2px solid {TAB_BUTTON_FOCUS_BORDER_COLOR_HEX};
            }}
        """
        
        # Install event filter on button container to handle keyboard events
        self.button_container.installEventFilter(self)

    def refresh_theme_styles(self):
        """Refresh tab chrome using current theme constants from thumbnail_constants."""
        self.button_container.setStyleSheet(f"""
            QWidget {{
                border: 2px solid transparent;
            }}
            QWidget:focus {{
                border: 2px solid {tc.TAB_BUTTON_FOCUS_BORDER_COLOR_HEX};
                border-radius: 4px;
            }}
        """)
        self.tab_style = f"""
            QPushButton {{
                background-color: {tc.DIALOG_BACKGROUND_HEX};
                color: {tc.DIALOG_TEXT_COLOR_HEX};
                border: 1px solid {tc.BORDER_DEFAULT_HEX};
                border-radius: 4px;
                padding: 6px 12px;
                text-align: left;
            }}
            QPushButton:hover {{
                background-color: {tc.TAB_BUTTON_HOVER_BG_HEX};
            }}
            QPushButton:pressed {{
                background-color: {tc.WIDGET_BG_HOVER_HEX};
            }}
            QPushButton:checked {{
                background-color: {tc.BUTTON_BG_DEFAULT_HEX};
                border-left: 2px solid {tc.TAB_BUTTON_FOCUS_BORDER_COLOR_HEX};
            }}
        """
        for button in self.buttons:
            button.setStyleSheet(self.tab_style)
        self._updateAllButtonStyles()
    
    def addTab(self, widget, label, icon=None):
        """Add a tab with the given widget and label. Optionally include an icon that will only show for the active tab."""
        index = len(self.tabs)
        
        # Extract icon from label if present (icon is typically at the end after a space)
        # If icon parameter is provided, use it; otherwise try to extract from label
        base_label = label
        if icon:
            # Icon provided explicitly
            self.tab_icons[index] = icon
        else:
            # Try to extract icon from label (look for emoji at the end)
            label_parts = label.split()
            if label_parts:
                # Check if last part might be an emoji (single character or emoji)
                last_part = label_parts[-1]
                # Simple heuristic: if it's a single character that's not alphanumeric, it might be an emoji
                # Or if it contains emoji characters (Unicode ranges)
                if len(last_part) <= 2 or any(ord(c) > 0x1F000 for c in last_part):
                    # Likely an emoji, extract it
                    self.tab_icons[index] = last_part
                    base_label = ' '.join(label_parts[:-1])
        
        # Store base label without icon
        self.tabs.append((widget, base_label))
        self.stacked_widgets.append(widget)
        
        # Get label text (with icon only if this is the active tab)
        display_label = self._getTabLabel(index, base_label)
        
        # Create button for tab - not individually focusable; fixed width aligns the column
        button = QPushButton(display_label)
        button.setCheckable(True)
        button.setFocusPolicy(Qt.NoFocus)  # Buttons not individually focusable
        button.setFixedWidth(self.SIDEBAR_BUTTON_WIDTH)
        button.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        button.setStyleSheet(self.tab_style)
        # Add to button group to ensure mutual exclusivity
        self.button_group.addButton(button, index)
        # Connect clicked signal - setCurrentIndex will handle checked state
        button.clicked.connect(lambda checked, idx=index: self.setCurrentIndex(idx))
        self.buttons.append(button)
        
        # Add button to flow layout (will wrap automatically)
        self.button_layout.addWidget(button)
        
        # Add widget to stacked layout (initially hidden)
        widget.setParent(self.stacked_widget)
        self.stacked_layout.addWidget(widget)
        widget.hide()
        
        # Set first tab as current if this is the first tab
        if index == 0:
            self.setCurrentIndex(0)
    
    def eventFilter(self, obj, event):
        """Handle keyboard events for arrow key navigation"""
        if obj == self.button_container:
            if event.type() == QEvent.Type.KeyPress:
                key = event.key()
                if key in (Qt.Key_Left, Qt.Key_Right, Qt.Key_Up, Qt.Key_Down):
                    self._handleArrowKey(key)
                    return True
                elif key == Qt.Key_Tab or key == Qt.Key_Backtab:
                    # Allow normal tab navigation to move focus away
                    return False
        return super().eventFilter(obj, event)
    
    def _handleArrowKey(self, key):
        """Handle arrow key navigation - changes active tab directly (vertical column)"""
        if not self.buttons:
            return
        
        # Use current_index as the starting point
        if self.current_index < 0:
            self.current_index = 0
        
        # Calculate new position based on arrow key (vertical column navigation)
        if key == Qt.Key_Up:
            new_index = self.current_index - 1
            if new_index < 0:
                new_index = len(self.buttons) - 1  # Wrap to bottom
        elif key == Qt.Key_Down:
            new_index = self.current_index + 1
            if new_index >= len(self.buttons):
                new_index = 0  # Wrap to top
        elif key == Qt.Key_Left or key == Qt.Key_Right:
            # Left/Right keys don't navigate in vertical column layout
            return
        else:
            return
        
        # Change active tab directly
        self.setCurrentIndex(new_index)
    
    def _updateButtonStyle(self, index):
        """Update button style - only active tab is highlighted"""
        if index < 0 or index >= len(self.buttons):
            return
        
        button = self.buttons[index]
        # Button group ensures only one is checked, so we just need to update style
        # The checked state is managed by the button group
        
        # Build style string - buttons size to content
        # Include checked state styling so it works with button group
        base_style = f"""
            QPushButton {{
                background-color: {tc.DIALOG_BACKGROUND_HEX};
                color: {tc.DIALOG_TEXT_COLOR_HEX};
                border: 1px solid {tc.BORDER_DEFAULT_HEX};
                border-radius: 4px;
                padding: 6px 12px;
                text-align: left;
            }}
            QPushButton:hover {{
                background-color: {tc.TAB_BUTTON_HOVER_BG_HEX};
            }}
            QPushButton:pressed {{
                background-color: {tc.WIDGET_BG_HOVER_HEX};
            }}
            QPushButton:checked {{
                background-color: {tc.TAB_BUTTON_FOCUS_BACKGROUND_COLOR_HEX}; 
                border-left: 2px solid {tc.TAB_BUTTON_FOCUS_BORDER_COLOR_HEX};
                border-right: 1px inset solid {tc.TAB_BUTTON_FOCUS_BORDER_COLOR_HEX};
                border-bottom: 1px inset solid {tc.TAB_BUTTON_FOCUS_BORDER_COLOR_HEX};
                border-top: 1px inset solid {tc.TAB_BUTTON_FOCUS_BORDER_COLOR_HEX};
            }}
        """
        
        button.setStyleSheet(base_style)
    
    def _getTabLabel(self, index, base_label):
        """Get the label text for a tab, with icon only if it's the active tab"""
        # If this tab has an icon and is active, include it
        if index == self.current_index and index in self.tab_icons:
            return f"{base_label} {self.tab_icons[index]}"
        else:
            # Return base label without icon
            return base_label
    
    def _updateTabLabels(self):
        """Update all tab button labels to show icon only for active tab"""
        for i, (widget, base_label) in enumerate(self.tabs):
            if i < len(self.buttons):
                display_label = self._getTabLabel(i, base_label)
                self.buttons[i].setText(display_label)
    
    def showEvent(self, event):
        """Handle show event to update layout with proper width"""
        super().showEvent(event)
        # Update layout after widget is shown and has proper dimensions
        QTimer.singleShot(50, self._updateTabLayout)
    
    def resizeEvent(self, event):
        """Handle resize to update flow layout"""
        super().resizeEvent(event)
        if event and self.button_container.width() > 0:
            available_width = self.button_container.width() - 40
            self.button_layout.updateColumns(available_width)
            # Update button styles after layout change
            self._updateAllButtonStyles()
    
    def _updateTabLayout(self):
        """Update tab layout after widget is shown"""
        if self.button_container.width() > 0:
            available_width = self.button_container.width() - 40
            self.button_layout.updateColumns(available_width)
            # Update button styles after layout change
            self._updateAllButtonStyles()
    
    def _updateAllButtonStyles(self):
        """Update styles for all buttons"""
        for i in range(len(self.buttons)):
            self._updateButtonStyle(i)
    
    def setCurrentIndex(self, index):
        """Set the current tab index"""
        # Ensure index is an integer (reject booleans - bool is subclass of int in Python!)
        if type(index) is not int:
            return
        if index < 0 or index >= len(self.tabs):
            return
        
        # Hide current widget
        if self.current_index >= 0:
            self.stacked_widgets[self.current_index].hide()
        
        # Show new widget
        self.current_index = index
        self.stacked_widgets[index].show()
        
        # Update all button labels to show icon only for active tab
        self._updateTabLabels()
        
        # Button group will automatically uncheck others and check this one
        self.buttons[index].setChecked(True)
        self._updateButtonStyle(index)
        
        # Update styles for all buttons to ensure correct highlighting
        for i in range(len(self.buttons)):
            if i != index:
                self._updateButtonStyle(i)
        
        # Emit signal
        self.currentChanged.emit(index)
    
    def currentIndex(self):
        """Get the current tab index"""
        # Ensure we always return an integer (handle case where current_index might be False/None - use type() not isinstance() because bool is subclass of int!)
        if type(self.current_index) is not int:
            return -1
        return self.current_index
    
    def widget(self, index):
        """Get the widget at the given index"""
        if 0 <= index < len(self.stacked_widgets):
            return self.stacked_widgets[index]
        return None
    
    def indexOf(self, widget):
        """Get the index of the given widget"""
        try:
            return self.stacked_widgets.index(widget)
        except ValueError:
            return -1

