#!/usr/bin/env python3
"""
Right Sidebar Combined Widget - Combines Information and Shortcuts in a single resizable right_sidebar
"""

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QSplitter, QSizePolicy
)

from combined_sidebar_widget import HeaderWidget
from information_sidebar import InformationSidebar
from shortcuts_sidebar import ShortcutsSidebar
from theme_service import get_active_theme


class RightSidebarCombinedWidget(QWidget):
    """
    Combined right_sidebar widget containing Shortcuts (top) and Information (bottom) sections.
    Both sub-widgets can be visible at the same time; Shortcuts is on top when both showing.
    Information and Shortcuts are independent - either or both can be visible.
    """

    # Signal emitted when splitter is resized (for layout recalculation)
    widget_resized = Signal()
    # Signal emitted when Information or Shortcuts visibility changes (for main window to update right sidebar)
    visibility_changed = Signal()

    def __init__(self, main_window, parent=None):
        super().__init__(parent)
        self.main_window = main_window
        settings = main_window.config.load_settings()
        # information_visible: load from config (I key)
        self.information_visible = settings.get('information_sidebar_visible', False)
        self.shortcuts_visible = settings.get('shortcuts_sidebar_visible', False)
        saved = settings.get('shortcuts_splitter_sizes', [250, 150])
        self.saved_splitter_sizes = saved if isinstance(saved, list) and len(saved) == 2 and sum(saved) > 0 else [250, 150]

        self.information_widget = None
        self.shortcuts_widget = None
        self.information_section = None
        self.shortcuts_section = None
        self.information_header = None
        self.shortcuts_header = None
        self.information_content = None
        self.shortcuts_content = None

        self.setFocusPolicy(Qt.NoFocus)
        self.setup_ui()

    def setup_ui(self):
        """Setup the right_sidebar combined widget UI"""
        self.setMinimumWidth(250)
        self.setMaximumWidth(800)
        _th = get_active_theme()
        self.setStyleSheet(_th.right_sidebar_combined_stylesheet())

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Create vertical splitter for right_sidebar (Shortcuts on top, Information below)
        self.splitter = QSplitter(Qt.Vertical)
        self.splitter.setFocusPolicy(Qt.NoFocus)
        self.splitter.setHandleWidth(_th.view_border_width_px)
        self.splitter.setStyleSheet(_th.right_sidebar_inner_splitter_stylesheet())

        # Create Shortcuts section (top)
        self.shortcuts_section = self._create_section("Organize", "shortcuts")
        self.splitter.addWidget(self.shortcuts_section)

        # Create and add Information widget (bottom) - InformationSidebar has its own header
        self.information_widget = InformationSidebar(self.main_window, self)
        self.information_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        # Override information header: toggle information section only
        self.information_widget.information_header.hide_button.clicked.disconnect()
        self.information_widget.information_header.hide_button.clicked.connect(self._toggle_information)
        self.splitter.addWidget(self.information_widget)
        self.information_widget.setVisible(self.information_visible)
        self.information_widget.information_header.hide_button.setText("−" if self.information_visible else "+")

        # Set initial sizes - Shortcuts (top) gets less space, Information (bottom) gets more when both visible
        self.splitter.setSizes([150, 250])

        self.splitter.splitterMoved.connect(self._on_splitter_moved)
        layout.addWidget(self.splitter)

        # Create and embed Shortcuts widget
        self.shortcuts_widget = ShortcutsSidebar(self.main_window, self)
        self.shortcuts_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.shortcuts_header.hide_button.clicked.connect(self._toggle_shortcuts)
        self.shortcuts_content.layout().addWidget(self.shortcuts_widget)
        self.shortcuts_widget.show()

        # Apply initial visibility for Shortcuts
        self.shortcuts_content.setVisible(self.shortcuts_visible)
        self.shortcuts_header.hide_button.setText("−" if self.shortcuts_visible else "+")
        self._update_splitter_sizes()

    def _create_section(self, title, section_type):
        """Create a section with header and content area (for Shortcuts)"""
        section = QWidget()
        section.setFocusPolicy(Qt.NoFocus)
        section.setProperty("section_type", section_type)

        sect_layout = QVBoxLayout(section)
        sect_layout.setContentsMargins(0, 0, 0, 0)
        sect_layout.setSpacing(0)

        header = HeaderWidget(title, omit_left_border=True)
        header.setFocusPolicy(Qt.NoFocus)
        self.shortcuts_header = header

        sect_layout.addWidget(header)

        content_area = QWidget()
        content_area.setFocusPolicy(Qt.NoFocus)
        content_area.setProperty("content_area", True)
        content_layout = QVBoxLayout(content_area)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)
        content_area.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        self.shortcuts_content = content_area

        sect_layout.addWidget(content_area)
        return section

    def _toggle_information(self):
        """Toggle Information section visibility"""
        self.information_visible = not self.information_visible
        self.information_widget.setVisible(self.information_visible)
        self.information_widget.information_header.hide_button.setText("−" if self.information_visible else "+")
        self.main_window.config.update_setting('information_sidebar_visible', self.information_visible)
        self._update_splitter_sizes()
        self.visibility_changed.emit()
        self.widget_resized.emit()

    def _toggle_shortcuts(self):
        """Toggle Shortcuts section visibility (also triggered by O key)"""
        self.shortcuts_visible = not self.shortcuts_visible
        self.shortcuts_content.setVisible(self.shortcuts_visible)
        self.shortcuts_header.hide_button.setText("−" if self.shortcuts_visible else "+")
        self._update_splitter_sizes()
        self.main_window.config.update_setting('shortcuts_sidebar_visible', self.shortcuts_visible)
        self.visibility_changed.emit()
        self.widget_resized.emit()

    def set_shortcuts_visible(self, visible):
        """Set Shortcuts visibility programmatically (e.g. from O key)"""
        if self.shortcuts_visible != visible:
            self.shortcuts_visible = visible
            self.shortcuts_content.setVisible(visible)
            self.shortcuts_header.hide_button.setText("−" if visible else "+")
            if visible and self.shortcuts_widget and hasattr(self.shortcuts_widget, 'refresh_shortcuts'):
                self.shortcuts_widget.refresh_shortcuts()
            self._update_splitter_sizes()
            self.main_window.config.update_setting('shortcuts_sidebar_visible', visible)
            self.visibility_changed.emit()
            self.widget_resized.emit()

    def is_shortcuts_visible(self):
        """Check if Shortcuts section is visible"""
        return self.shortcuts_visible

    def set_information_visible(self, visible):
        """Set Information visibility programmatically (e.g. from I key)"""
        if self.information_visible != visible:
            self.information_visible = visible
            self.information_widget.setVisible(visible)
            self.information_widget.information_header.hide_button.setText("−" if visible else "+")
            self._update_splitter_sizes()
            self.main_window.config.update_setting('information_sidebar_visible', visible)
            self.visibility_changed.emit()
            self.widget_resized.emit()

    def is_information_visible(self):
        """Check if Information section is visible"""
        return self.information_visible

    def _update_splitter_sizes(self):
        """Update splitter sizes based on which panes are visible. Splitter order: [Shortcuts, Information]."""
        if not self.information_visible and not self.shortcuts_visible:
            return
        h = self.height() if self.height() > 0 else 200
        if not self.information_visible:
            self.splitter.setSizes([h, 0])  # Shortcuts gets all
        elif not self.shortcuts_visible:
            self.splitter.setSizes([0, h])  # Information gets all
        else:
            if self.saved_splitter_sizes and len(self.saved_splitter_sizes) == 2:
                saved_total = sum(self.saved_splitter_sizes)
                if saved_total > 0:
                    current_height = self.height()
                    scale_factor = current_height / saved_total
                    # saved: [information, shortcuts]; splitter: [shortcuts, information]
                    scaled_info = int(self.saved_splitter_sizes[0] * scale_factor)
                    scaled_shortcuts = int(self.saved_splitter_sizes[1] * scale_factor)
                    total_scaled = scaled_info + scaled_shortcuts
                    if total_scaled != current_height:
                        scaled_info += (current_height - total_scaled)
                    self.splitter.setSizes([scaled_shortcuts, scaled_info])
                else:
                    half = self.height() // 2
                    self.splitter.setSizes([half, half])
            else:
                half = self.height() // 2
                self.splitter.setSizes([half, half])

    def _on_splitter_moved(self):
        """Handle splitter resize - save sizes, update information text width, emit signal"""
        if self.information_visible and self.shortcuts_visible:
            sizes = self.splitter.sizes()  # [shortcuts, information]
            if len(sizes) == 2 and sizes[0] > 0 and sizes[1] > 0:
                # Config format: [information, shortcuts]
                self.saved_splitter_sizes = [sizes[1], sizes[0]]
                self.main_window.config.update_setting('shortcuts_splitter_sizes', self.saved_splitter_sizes)
        # Update information text width when splitter moves
        if self.information_widget and self.information_widget.info_text_edit and self.information_widget.info_text_edit.isVisible():
            w = self.information_widget.width()
            if w > 0:
                doc = self.information_widget.info_text_edit.document()
                doc.setTextWidth(w - 36)
                self.information_widget.info_text_edit.update()
        self.widget_resized.emit()

    def resizeEvent(self, event):
        """Handle resize events"""
        super().resizeEvent(event)
        QTimer.singleShot(10, self._update_splitter_sizes)
        self.widget_resized.emit()

    # Delegate to information widget for compatibility with toggle_information_display
    def show_info(self):
        """Show information (delegate to information widget)"""
        if self.information_widget:
            self.information_widget.show_info()

    def hide_info(self):
        """Hide information (delegate to information widget)"""
        if self.information_widget:
            self.information_widget.hide_info()

    def show_image_info_overlay(self):
        """Show image info overlay (delegate to information widget)"""
        if self.information_widget:
            self.information_widget.show_image_info_overlay()

    def hide_image_info_overlay(self):
        """Hide image info overlay (delegate to information widget)"""
        if self.information_widget:
            self.information_widget.hide_image_info_overlay()

    @property
    def info_text_edit(self):
        """Expose information's info_text_edit for ui_layout_manager compatibility"""
        return self.information_widget.info_text_edit if self.information_widget else None

    def refresh_theme_styles(self):
        """Reapply shell, headers, and embedded widgets after theme change."""
        th = get_active_theme()
        self.setStyleSheet(th.right_sidebar_combined_stylesheet())
        self.splitter.setHandleWidth(th.view_border_width_px)
        self.splitter.setStyleSheet(th.right_sidebar_inner_splitter_stylesheet())
        if getattr(self, "shortcuts_header", None):
            self.shortcuts_header.refresh_theme_styles()
        if self.shortcuts_widget:
            self.shortcuts_widget.refresh_theme_styles()
        if self.information_widget:
            self.information_widget.refresh_theme_styles()
