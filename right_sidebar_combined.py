#!/usr/bin/env python3
"""
Right Sidebar Combined Widget - Combines Organize, Information, and Jobs in a single resizable right_sidebar
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
    Combined right_sidebar widget containing Shortcuts (top), Information (middle),
    and Jobs (bottom) sections. Each section can be shown or hidden independently.
    """

    widget_resized = Signal()
    visibility_changed = Signal()

    def __init__(self, main_window, parent=None):
        super().__init__(parent)
        self.main_window = main_window
        settings = main_window.config.load_settings()
        self.information_visible = settings.get('information_sidebar_visible', False)
        self.shortcuts_visible = settings.get('shortcuts_sidebar_visible', False)
        self.jobs_visible = settings.get('jobs_visible', False)
        saved = settings.get('shortcuts_splitter_sizes', [150, 250, 120])
        if isinstance(saved, list) and len(saved) == 2 and sum(saved) > 0:
            # Legacy [information, shortcuts] -> [shortcuts, information, jobs]
            saved = [saved[1], saved[0], 120]
        self.saved_splitter_sizes = (
            saved
            if isinstance(saved, list) and len(saved) == 3 and sum(saved) > 0
            else [150, 250, 120]
        )

        self.information_widget = None
        self.shortcuts_widget = None
        self.jobs_widget = None
        self.information_section = None
        self.shortcuts_section = None
        self.jobs_section = None
        self.information_header = None
        self.shortcuts_header = None
        self.jobs_header = None
        self.information_content = None
        self.shortcuts_content = None
        self.jobs_content = None

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

        self.splitter = QSplitter(Qt.Vertical)
        self.splitter.setFocusPolicy(Qt.NoFocus)
        self.splitter.setHandleWidth(_th.view_border_width_px)
        self.splitter.setStyleSheet(_th.right_sidebar_inner_splitter_stylesheet())

        self.shortcuts_section = self._create_section("Organize", "shortcuts")
        self.splitter.addWidget(self.shortcuts_section)

        self.information_widget = InformationSidebar(self.main_window, self)
        self.information_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.information_widget.information_header.hide_button.clicked.disconnect()
        self.information_widget.information_header.hide_button.clicked.connect(self._toggle_information)
        self.splitter.addWidget(self.information_widget)
        self.information_widget.setVisible(self.information_visible)
        self.information_widget.information_header.hide_button.setText(
            "−" if self.information_visible else "+"
        )

        self.jobs_section = self._create_section("Jobs", "jobs")
        self.splitter.addWidget(self.jobs_section)

        self.splitter.setSizes([150, 250, 120])
        self.splitter.splitterMoved.connect(self._on_splitter_moved)
        layout.addWidget(self.splitter)

        self.shortcuts_widget = ShortcutsSidebar(self.main_window, self)
        self.shortcuts_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.shortcuts_content.layout().addWidget(self.shortcuts_widget)
        self.shortcuts_widget.show()

        self.shortcuts_content.setVisible(self.shortcuts_visible)
        self.shortcuts_header.hide_button.setText("−" if self.shortcuts_visible else "+")

        self.jobs_content.setVisible(self.jobs_visible)
        self.jobs_header.hide_button.setText("−" if self.jobs_visible else "+")
        self._update_splitter_sizes()

    def _create_section(self, title, section_type):
        """Create a section with header and content area (for Shortcuts or Jobs)"""
        section = QWidget()
        section.setFocusPolicy(Qt.NoFocus)
        section.setProperty("section_type", section_type)

        sect_layout = QVBoxLayout(section)
        sect_layout.setContentsMargins(0, 0, 0, 0)
        sect_layout.setSpacing(0)

        header = HeaderWidget(title, omit_left_border=True)
        header.setFocusPolicy(Qt.NoFocus)
        if section_type == "shortcuts":
            self.shortcuts_header = header
            header.hide_button.clicked.connect(self._toggle_shortcuts)
        else:
            self.jobs_header = header
            header.hide_button.clicked.connect(self._toggle_jobs)

        sect_layout.addWidget(header)

        content_area = QWidget()
        content_area.setFocusPolicy(Qt.NoFocus)
        content_area.setProperty("content_area", True)
        content_layout = QVBoxLayout(content_area)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)
        content_area.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        if section_type == "shortcuts":
            self.shortcuts_content = content_area
        else:
            self.jobs_content = content_area

        sect_layout.addWidget(content_area)
        return section

    def _pane_visibility(self) -> list[bool]:
        return [self.shortcuts_visible, self.information_visible, self.jobs_visible]

    def _toggle_information(self):
        """Toggle Information section visibility"""
        self.information_visible = not self.information_visible
        self.information_widget.setVisible(self.information_visible)
        self.information_widget.information_header.hide_button.setText(
            "−" if self.information_visible else "+"
        )
        self.main_window.config.update_setting(
            'information_sidebar_visible', self.information_visible
        )
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

    def _toggle_jobs(self):
        """Toggle Jobs section visibility (also triggered by J key)"""
        self.set_jobs_visible(not self.jobs_visible)

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

    def set_jobs_widget(self, jobs_widget):
        """Set the jobs widget in the jobs section"""
        self.jobs_widget = jobs_widget
        if self.jobs_widget:
            if self.jobs_widget.parent():
                self.jobs_widget.setParent(None)
            self.jobs_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
            layout = self.jobs_content.layout()
            layout.addWidget(self.jobs_widget)
            self.jobs_widget.show()

    def set_jobs_visible(self, visible):
        """Set Jobs visibility programmatically (e.g. from J key)"""
        if self.jobs_visible != visible:
            self.jobs_visible = visible
            self.jobs_content.setVisible(visible)
            self.jobs_header.hide_button.setText("−" if visible else "+")
            if visible and self.jobs_widget and hasattr(self.jobs_widget, 'refresh_table'):
                self.jobs_widget.refresh_table()
            self._update_splitter_sizes()
            self.main_window.config.update_setting('jobs_visible', visible)
            self.visibility_changed.emit()
            self.widget_resized.emit()
        elif visible and self.jobs_widget:
            self.jobs_widget.show()
            if hasattr(self.jobs_widget, 'refresh_table'):
                self.jobs_widget.refresh_table()

    def is_jobs_visible(self):
        """Check if Jobs section is visible"""
        return self.jobs_visible

    def _update_splitter_sizes(self):
        """Update splitter sizes based on which panes are visible. Order: [shortcuts, information, jobs]."""
        vis = self._pane_visibility()
        if not any(vis):
            return
        current_height = max(self.height(), 1)
        visible_indices = [i for i, v in enumerate(vis) if v]
        if len(visible_indices) == 1:
            sizes = [current_height if v else 0 for v in vis]
            self.splitter.setSizes(sizes)
            return

        saved = self.saved_splitter_sizes
        if saved and len(saved) == 3:
            vis_saved = [saved[i] if vis[i] else 0 for i in range(3)]
            total_saved = sum(vis_saved)
            if total_saved > 0:
                scaled = [
                    int(vis_saved[i] * current_height / total_saved) if vis[i] else 0
                    for i in range(3)
                ]
                total_scaled = sum(scaled)
                if total_scaled != current_height and visible_indices:
                    scaled[visible_indices[-1]] += current_height - total_scaled
                self.splitter.setSizes(scaled)
                return

        each = current_height // len(visible_indices)
        sizes = [0, 0, 0]
        for i in visible_indices:
            sizes[i] = each
        remainder = current_height - sum(sizes)
        if remainder and visible_indices:
            sizes[visible_indices[-1]] += remainder
        self.splitter.setSizes(sizes)

    def _on_splitter_moved(self):
        """Handle splitter resize - save sizes, update information text width, emit signal"""
        vis = self._pane_visibility()
        if all(vis):
            sizes = self.splitter.sizes()
            if len(sizes) == 3 and all(s > 0 for s in sizes):
                self.saved_splitter_sizes = sizes.copy()
                self.main_window.config.update_setting(
                    'shortcuts_splitter_sizes', self.saved_splitter_sizes
                )
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
        if getattr(self, "jobs_header", None):
            self.jobs_header.refresh_theme_styles()
        if self.shortcuts_widget:
            self.shortcuts_widget.refresh_theme_styles()
        if self.information_widget:
            self.information_widget.refresh_theme_styles()
