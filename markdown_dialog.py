#!/usr/bin/env python3
"""
Common Markdown Dialog
Displays markdown-formatted text using Qt's built-in markdown display facilities
"""

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QLabel, QPushButton, QHBoxLayout,
    QTextEdit, QSizePolicy, QApplication
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont

from thumbnails.thumbnail_constants import (
    DIALOG_TEXT_COLOR_HEX, BORDER_DEFAULT_HEX,
    BUTTON_BG_DEFAULT_HEX,
)
from theme.theme_service import get_active_theme
from utils import get_button_style


class MarkdownDialog(QDialog):
    """Common dialog for displaying markdown-formatted content"""

    def __init__(self, title, markdown_content, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        
        self.setup_ui()
        self.load_content(markdown_content)

        # Make the window take up the whole screen minus 10% margins all around
        # and center it on the physical screen
        self._resize_to_screen_with_margin()

    def _resize_to_screen_with_margin(self):
        """Resize the dialog to fill the entire available screen minus 10% margins all around, centered"""
        # Get the screen to use (primary screen, or parent's screen if possible)
        app = QApplication.instance()
        screen = None

        if self.parent() is not None:
            # Try to get screen of parent widget
            screen = self.parent().window().windowHandle().screen()
        if not screen and app:
            screen = app.primaryScreen()
        if not screen:
            return
        
        geometry = screen.availableGeometry()
        width = geometry.width()
        height = geometry.height()
        x = geometry.x()
        y = geometry.y()

        # Calculate margins: 10% of width/height on each side
        margin_w = int(width * 0.10)
        margin_h = int(height * 0.10)

        # Calculate new size (screen minus margins)
        new_width = width - 2 * margin_w
        new_height = height - 2 * margin_h

        # Center the window on the screen
        new_x = x + (width - new_width) // 2
        new_y = y + (height - new_height) // 2

        self.setGeometry(new_x, new_y, new_width, new_height)
        # Set a reasonable minimum size to allow resizing
        self.setMinimumSize(400, 300)

    def setup_ui(self):
        """Setup the dialog UI"""
        th = get_active_theme()
        self.setStyleSheet(
            f"QDialog {{ background-color: {th.dialog_background_hex}; color: {th.dialog_text_color_hex}; }}\n"
            + get_button_style()
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)

        # Title
        title = QLabel(self.windowTitle())
        title.setAlignment(Qt.AlignCenter)
        title_font = QFont()
        title_font.setPointSize(18)
        title_font.setBold(True)
        title.setFont(title_font)
        layout.addWidget(title)

        # Markdown content area
        self.content_area = QTextEdit()
        self.content_area.setReadOnly(True)
        self.content_area.setAcceptRichText(True)
        self.content_area.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        # Set a reasonable font
        content_font = QFont()
        content_font.setPointSize(12)
        self.content_area.setFont(content_font)
        # Style the text area (uses base colors from thumbnail_constants)
        self.content_area.setStyleSheet(f"""
            QTextEdit {{
                background-color: {BUTTON_BG_DEFAULT_HEX};
                color: {DIALOG_TEXT_COLOR_HEX};
                border: 1px solid {BORDER_DEFAULT_HEX};
                border-radius: 4px;
                padding: 10px;
            }}
        """)
        layout.addWidget(self.content_area)

        # Close button
        button_layout = QHBoxLayout()
        button_layout.addStretch()

        close_button = QPushButton("Close")
        close_button.setDefault(True)
        close_button.clicked.connect(self.accept)
        button_layout.addWidget(close_button)
        button_layout.addStretch()

        layout.addLayout(button_layout)
    
    def showEvent(self, event):
        """Override showEvent to ensure close button has focus when dialog is shown"""
        super().showEvent(event)
        # Find and focus the close button
        for widget in self.findChildren(QPushButton):
            if widget.text() == "Close":
                widget.setFocus()
                break

    def load_content(self, markdown_content):
        """Load markdown content into the text area"""
        self.content_area.setMarkdown(markdown_content)


def show_markdown_dialog(title, markdown_content, parent=None):
    """Convenience function to show a markdown dialog"""
    dialog = MarkdownDialog(title, markdown_content, parent)
    dialog.exec()
