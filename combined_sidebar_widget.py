#!/usr/bin/env python3
"""
Combined Sidebar Widget - Combines tree view and preview in a single resizable widget
"""

from PySide6.QtCore import Qt, QSize, Signal, QTimer
from PySide6.QtGui import QFont, QColor, QPalette
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, 
    QSplitter, QScrollArea, QFrame, QSizePolicy
)
import thumbnail_constants as tc
from thumbnail_constants import GREEN, RESET, YELLOW
from theme_service import get_active_theme

class HeaderWidget(QFrame):
    """Header widget with title and hide button"""

    def __init__(
        self,
        title,
        parent=None,
        *,
        omit_right_border: bool = False,
        omit_left_border: bool = False,
    ):
        super().__init__(parent)
        self.title = title
        self.omit_right_border = omit_right_border
        self.omit_left_border = omit_left_border
        self.hide_button = None
        self.setup_ui()
        
    def setup_ui(self):
        """Setup the header UI"""
        self.setFocusPolicy(Qt.NoFocus)
        self.setFixedHeight(30)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(8)
        
        # Title label
        self.title_label = QLabel(self.title)
        self.title_label.setFocusPolicy(Qt.NoFocus)
        layout.addWidget(self.title_label)
        
        layout.addStretch()
        
        # Hide button
        self.hide_button = QPushButton("−")
        self.hide_button.setFixedSize(20, 20)
        self.hide_button.setFocusPolicy(Qt.NoFocus)
        layout.addWidget(self.hide_button)
        self.refresh_theme_styles()

    def _qframe_stylesheet(self, background_color_hex: str) -> str:
        """QFrame-only sheet: borders and per-corner radii respect omit_* flags."""
        b = tc.SIDEBAR_HEADER_BORDER_HEX
        left = (
            f"border-left: 1px solid {b};"
            if not self.omit_left_border
            else "border-left: none;"
        )
        right = (
            f"border-right: 1px solid {b};"
            if not self.omit_right_border
            else "border-right: none;"
        )
        border_css = f"""
                border-top: 1px solid {b};
                {left}
                {right}
                border-bottom: 1px solid {b};
            """
        r = 3
        if not self.omit_left_border and not self.omit_right_border:
            radius_css = f"border-radius: {r}px;"
        else:
            tl = 0 if self.omit_left_border else r
            tr = 0 if self.omit_right_border else r
            bl = 0 if self.omit_left_border else r
            br = 0 if self.omit_right_border else r
            radius_css = f"""
                border-top-left-radius: {tl}px;
                border-top-right-radius: {tr}px;
                border-bottom-left-radius: {bl}px;
                border-bottom-right-radius: {br}px;
            """
        return f"""
            QFrame {{
                background-color: {background_color_hex};
                {border_css}
                {radius_css}
            }}
        """

    def refresh_theme_styles(self):
        """Reapply styles from theme-synced thumbnail_constants (call after theme change)."""
        self.setStyleSheet(self._qframe_stylesheet(tc.SIDEBAR_HEADER_BG_HEX))
        self.title_label.setStyleSheet(f"""
            QLabel {{
                color: {tc.SIDEBAR_HEADER_TEXT_HEX};
                font-weight: bold;
                font-size: 12px;
                border-width: 0px;
            }}
        """)
        titlebar = QColor(tc.SIDEBAR_HEADER_BG_HEX)
        if not titlebar.isValid():
            titlebar = QColor("#2b2b2b")
        # Hide chip: fill/border derived from titlebar (lighter than bar; hover lighter still)
        hb_bg = titlebar.lighter(200).name()
        hb_hover = titlebar.lighter(300).name()
        hb_pressed = titlebar.lighter(160).name()
        hb_border = titlebar.lighter(160).name()
        hb_border_hover = titlebar.lighter(180).name()
        self.hide_button.setStyleSheet(f"""
            QPushButton {{
                background-color: {hb_bg};
                border: 1px solid {hb_border};
                border-radius: 3px;
                color: {tc.SIDEBAR_HEADER_TEXT_HEX};
                font-weight: bold;
                min-width: 20px;
                padding: 0px;
            }}
            QPushButton:hover {{
                background-color: {hb_hover};
                border-color: {hb_border_hover};
            }}
            QPushButton:pressed {{
                background-color: {hb_pressed};
                border-color: {hb_border};
            }}
        """)

class CombinedSidebarWidget(QWidget):
    """Combined widget containing tree view and preview with resizable sections"""
    
    # Signals
    tree_visibility_changed = Signal(bool)
    preview_visibility_changed = Signal(bool)
    jobs_visibility_changed = Signal(bool)
    widget_resized = Signal()
    
    def __init__(self, main_window, parent=None):
        super().__init__(parent)
        self.main_window = main_window
        self.tree_visible = True
        self.preview_visible = True
        self.jobs_visible = False
        self.tree_widget = None
        self.preview_widget = None
        self.jobs_widget = None
        
        # Store saved splitter sizes for session persistence
        # Format: [tree_size, preview_size, jobs_size] or None if not yet set
        self.saved_splitter_sizes = None
        
        # Set focus policy to be in tab order
        # self.setFocusPolicy(Qt.StrongFocus)
        self.setFocusPolicy(Qt.NoFocus)
        
        self.setup_ui()
        
    def focusInEvent(self, event):
        """Handle focus in events - forward focus to tree view if visible"""
        super().focusInEvent(event)
        if self.tree_visible and self.tree_widget:
            # Forward focus to the tree view
            self.tree_widget.setFocus()
        elif self.preview_visible and self.preview_widget:
            # If only preview is visible, focus the preview
            self.preview_widget.setFocus()
        elif self.jobs_visible and self.jobs_widget:
            self.jobs_widget.setFocus()
        
    def setup_ui(self):
        """Setup the combined widget UI"""
        self.setMinimumWidth(250)
        self.setMaximumWidth(500)
        
        # Main layout
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # Create vertical splitter
        self.splitter = QSplitter(Qt.Vertical)
        self.splitter.setHandleWidth(get_active_theme().view_border_width_px)
        self._apply_splitter_theme_styles()
        
        # Create tree section
        self.tree_section = self._create_section("File Tree", "tree")
        
        # Create preview section  
        self.preview_section = self._create_section("Preview", "preview")

        # Create jobs section (below preview; visibility independent of tree/preview)
        self.jobs_section = self._create_section("Jobs", "jobs")
        
        # Add sections to splitter
        self.splitter.addWidget(self.tree_section)
        self.splitter.addWidget(self.preview_section)
        self.splitter.addWidget(self.jobs_section)
        
        # Set initial sizes (tree / preview / jobs)
        self.splitter.setSizes([160, 160, 120])
        
        # Connect splitter resize events
        self.splitter.splitterMoved.connect(self._on_splitter_moved)
        
        layout.addWidget(self.splitter)

        self.jobs_content.setVisible(False)
        self.jobs_header.hide_button.setText("+")
        
    def _apply_splitter_theme_styles(self):
        w = get_active_theme().view_border_width_px
        self.splitter.setHandleWidth(w)
        self.splitter.setStyleSheet(f"""
            QSplitter::handle {{
                background-color: {tc.SIDEBAR_SPLITTER_HANDLE_HEX};
                border: none;
            }}
            QSplitter::handle:horizontal {{
                width: {w}px;
            }}
            QSplitter::handle:vertical {{
                height: {w}px;
            }}
        """)

    def refresh_theme_styles(self):
        """Reapply header and splitter styles after global theme change."""
        self._apply_splitter_theme_styles()
        if getattr(self, "tree_header", None):
            self.tree_header.refresh_theme_styles()
        if getattr(self, "preview_header", None):
            self.preview_header.refresh_theme_styles()
        if getattr(self, "jobs_header", None):
            self.jobs_header.refresh_theme_styles()
        if getattr(self, "tree_widget", None):
            self._update_tree_header_focus(self.tree_widget.hasFocus())

    def _create_section(self, title, section_type):
        """Create a section with header and content area"""
        section = QWidget()
        section.setProperty("section_type", section_type)
        
        layout = QVBoxLayout(section)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # Create header (no inner edge border where titlebar meets main content / splitter)
        header = HeaderWidget(title, omit_right_border=True)
        if section_type == "tree":
            self.tree_header = header
            header.hide_button.clicked.connect(self._toggle_tree)
        elif section_type == "preview":
            self.preview_header = header
            header.hide_button.clicked.connect(self._toggle_preview)
        else:
            self.jobs_header = header
            header.hide_button.clicked.connect(self._toggle_jobs)
        
        layout.addWidget(header)
        
        # Create content area
        content_area = QWidget()
        content_area.setProperty("content_area", True)
        content_layout = QVBoxLayout(content_area)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)
        
        # Set size policy to expand
        content_area.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        
        # For preview section, align content to top
        if section_type == "preview":
            content_layout.setAlignment(Qt.AlignTop)
        
        if section_type == "tree":
            self.tree_content = content_area
        elif section_type == "preview":
            self.preview_content = content_area
        else:
            self.jobs_content = content_area
            
        layout.addWidget(content_area)
        
        return section
        
    def set_tree_widget(self, tree_widget):
        """Set the tree widget in the tree section"""
        self.tree_widget = tree_widget
        if self.tree_widget:
            # Remove from old parent if any
            if self.tree_widget.parent():
                self.tree_widget.setParent(None)
            
            # Set size policy to expand
            self.tree_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
            
            # Add to tree content area
            layout = self.tree_content.layout()
            layout.addWidget(self.tree_widget)
            
            # Ensure the tree widget is visible
            self.tree_widget.show()
            
            # Connect focus events to update header color
            self._connect_tree_focus_events()
            
            # Update initial header color based on current focus state
            self._update_tree_header_focus(self.tree_widget.hasFocus())
            
    def set_preview_widget(self, preview_widget):
        """Set the preview widget in the preview section"""
        self.preview_widget = preview_widget
        if self.preview_widget:
            # Remove from old parent if any
            if self.preview_widget.parent():
                self.preview_widget.setParent(None)
            
            # Set size policy to expand
            self.preview_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
            
            # Add to preview content area
            layout = self.preview_content.layout()
            layout.addWidget(self.preview_widget)
            
            # Ensure the preview widget is visible
            self.preview_widget.show()

    def set_jobs_widget(self, jobs_widget):
        """Set the jobs widget in the jobs section"""
        self.jobs_widget = jobs_widget
        if self.jobs_widget:
            if self.jobs_widget.parent():
                self.jobs_widget.setParent(None)
            self.jobs_widget.setSizePolicy(
                QSizePolicy.Expanding, QSizePolicy.Expanding
            )
            layout = self.jobs_content.layout()
            layout.addWidget(self.jobs_widget)
            self.jobs_widget.show()
            
    def _toggle_tree(self):
        """Toggle tree visibility"""
        self.tree_visible = not self.tree_visible
        self.tree_content.setVisible(self.tree_visible)
        
        # Update header button text
        self.tree_header.hide_button.setText("−" if self.tree_visible else "+")
        
        # Update splitter sizes based on visibility
        self._update_splitter_sizes()
        
        # Emit signal
        self.tree_visibility_changed.emit(self.tree_visible)
        
        # If both are hidden, hide the entire widget
        self._update_overall_visibility()
        
        
    def _toggle_preview(self):
        """Toggle preview visibility"""
        self.preview_visible = not self.preview_visible
        self.preview_content.setVisible(self.preview_visible)
        
        # Update header button text
        self.preview_header.hide_button.setText("−" if self.preview_visible else "+")
        
        # Update splitter sizes based on visibility
        self._update_splitter_sizes()
        
        # Emit signal
        self.preview_visibility_changed.emit(self.preview_visible)
        
        # If all panes are hidden, hide the entire widget
        self._update_overall_visibility()

    def _toggle_jobs(self):
        """Toggle jobs pane visibility"""
        self.jobs_visible = not self.jobs_visible
        self.jobs_content.setVisible(self.jobs_visible)
        self.jobs_header.hide_button.setText("−" if self.jobs_visible else "+")
        self._update_splitter_sizes()
        self.jobs_visibility_changed.emit(self.jobs_visible)
        self._update_overall_visibility()
        
    def _pane_visibility(self) -> list[bool]:
        return [self.tree_visible, self.preview_visible, self.jobs_visible]

    def _update_splitter_sizes(self):
        """Update splitter sizes based on which panes are visible"""
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
    
    def _update_overall_visibility(self):
        """Update overall widget visibility based on section visibility"""
        if not any(self._pane_visibility()):
            self.hide()
            return
        mw = getattr(self, "main_window", None)
        if mw and getattr(mw, "current_view_mode", None) == "browse":
            self.hide()
            return
        self.show()
            
    def _on_splitter_moved(self):
        """Handle splitter resize events"""
        # Save the current splitter sizes when user manually adjusts them
        if all(self._pane_visibility()):
            current_sizes = self.splitter.sizes()
            if (
                len(current_sizes) == 3
                and all(s > 0 for s in current_sizes)
            ):
                self.saved_splitter_sizes = current_sizes.copy()
        
        self.widget_resized.emit()
        
    def set_tree_visible(self, visible):
        """Set tree visibility programmatically"""
        if self.tree_visible != visible:
            self.tree_visible = visible
            self.tree_content.setVisible(visible)
            
            # Update header button text
            self.tree_header.hide_button.setText("−" if visible else "+")
            
            # Update splitter sizes based on visibility
            self._update_splitter_sizes()
            
            # Emit signal
            self.tree_visibility_changed.emit(visible)
            
            # If both are hidden, hide the entire widget
            self._update_overall_visibility()
        elif visible and self.tree_widget:
            # If setting to visible and tree widget exists, ensure it's properly shown
            self.tree_widget.show()
        
            
    def set_preview_visible(self, visible):
        """Set preview visibility programmatically"""
        if self.preview_visible != visible:
            self.preview_visible = visible
            self.preview_content.setVisible(visible)
            
            # Update header button text
            self.preview_header.hide_button.setText("−" if visible else "+")
            
            # Update splitter sizes based on visibility
            self._update_splitter_sizes()
            
            # Emit signal
            self.preview_visibility_changed.emit(visible)
            
            # If both are hidden, hide the entire widget
            self._update_overall_visibility()
            
    def is_tree_visible(self):
        """Check if tree is visible"""
        return self.tree_visible
        
    def is_preview_visible(self):
        """Check if preview is visible"""
        return self.preview_visible

    def set_jobs_visible(self, visible):
        """Set jobs pane visibility programmatically"""
        if self.jobs_visible != visible:
            self.jobs_visible = visible
            self.jobs_content.setVisible(visible)
            self.jobs_header.hide_button.setText("−" if visible else "+")
            self._update_splitter_sizes()
            self.jobs_visibility_changed.emit(visible)
            self._update_overall_visibility()
        elif visible and self.jobs_widget:
            self.jobs_widget.show()

    def is_jobs_visible(self):
        """Check if jobs pane is visible"""
        return self.jobs_visible
        
    def resizeEvent(self, event):
        """Handle resize events"""
        super().resizeEvent(event)
        
        # Update splitter sizes when widget is resized
        QTimer.singleShot(10, self._update_splitter_sizes)
        
        self.widget_resized.emit()
    
    def _connect_tree_focus_events(self):
        """Connect focus events from tree widget to update header color"""
        if not self.tree_widget:
            return
        
        # Store original focus event handlers if they exist
        original_focus_in = getattr(self.tree_widget, 'focusInEvent', None)
        original_focus_out = getattr(self.tree_widget, 'focusOutEvent', None)
        
        def tree_focus_in(event):
            """Handle tree focus in event"""
            self._update_tree_header_focus(True)
            # Call original handler if it exists and is callable
            if callable(original_focus_in):
                original_focus_in(event)
            else:
                QWidget.focusInEvent(self.tree_widget, event)
        
        def tree_focus_out(event):
            """Handle tree focus out event"""
            self._update_tree_header_focus(False)
            # Call original handler if it exists and is callable
            if callable(original_focus_out):
                original_focus_out(event)
            else:
                QWidget.focusOutEvent(self.tree_widget, event)
        
        # Override focus event handlers
        self.tree_widget.focusInEvent = tree_focus_in
        self.tree_widget.focusOutEvent = tree_focus_out
    
    def _update_tree_header_focus(self, has_focus):
        """Update the tree header background color to indicate focus state"""
        if getattr(self, 'tree_header', None):
            bg_color = tc.TREE_HEADER_FOCUS_BG_HEX if has_focus else tc.SIDEBAR_HEADER_BG_HEX
            self.tree_header.setStyleSheet(self.tree_header._qframe_stylesheet(bg_color))
