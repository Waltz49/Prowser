#!/usr/bin/env python3
"""
Combined Sidebar Widget - Combines tree view and preview in a single resizable widget
"""

from PySide6.QtCore import Qt, QSize, Signal, QModelIndex, QTimer, QEvent, QPointF
from PySide6.QtGui import QFont, QColor, QPalette, QMouseEvent
from PySide6.QtWidgets import (
    QApplication,
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QSplitter, QScrollArea, QFrame, QSizePolicy, QTreeView,
)
import thumbnails.thumbnail_constants as tc
from thumbnails.thumbnail_constants import GREEN, RESET, YELLOW
from thumbnails.sidebar_pane_layout import (
    MIN_PANE_CONTENT,
    collapse_flags_for_target,
    ensure_pane_headers_visible,
    pane_min_height,
    redistribute_for_target_pane,
)
from theme.theme_service import get_active_theme

class HeaderWidget(QFrame):
    """Header widget with title and hide button"""

    title_double_clicked = Signal()
    title_clicked = Signal()

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
        self._single_click_timer = QTimer(self)
        self._single_click_timer.setSingleShot(True)
        self._single_click_timer.timeout.connect(self._emit_title_clicked)
        self.setup_ui()
        
    def setup_ui(self):
        """Setup the header UI"""
        self.setFocusPolicy(Qt.NoFocus)
        self.setFixedHeight(30)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(8)
        
        self.title_label = QLabel(self.title)
        self.title_label.setFocusPolicy(Qt.NoFocus)
        self.title_label.installEventFilter(self)
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

    def _titlebar_click_excludes_hide_button(self, event: QMouseEvent) -> bool:
        return self.hide_button is not None and self.hide_button.geometry().contains(
            event.position().toPoint()
        )

    def _emit_title_clicked(self) -> None:
        self.title_clicked.emit()

    def _map_title_label_mouse_event(self, event: QMouseEvent) -> QMouseEvent:
        pos = self.title_label.mapTo(self, event.position().toPoint())
        return QMouseEvent(
            event.type(),
            QPointF(pos),
            event.globalPosition(),
            event.button(),
            event.buttons(),
            event.modifiers(),
        )

    def eventFilter(self, watched, event) -> bool:
        if watched is self.title_label:
            et = event.type()
            if et in (
                QEvent.Type.MouseButtonPress,
                QEvent.Type.MouseButtonDblClick,
            ) and isinstance(event, QMouseEvent):
                mapped = self._map_title_label_mouse_event(event)
                if et == QEvent.Type.MouseButtonDblClick:
                    self.mouseDoubleClickEvent(mapped)
                else:
                    self.mousePressEvent(mapped)
                return True
        return super().eventFilter(watched, event)

    def mousePressEvent(self, event: QMouseEvent):
        """Defer single-click so double-click on the title bar is not swallowed."""
        if event.button() == Qt.LeftButton and not self._titlebar_click_excludes_hide_button(event):
            app = QApplication.instance()
            interval = app.doubleClickInterval() if app else 400
            self._single_click_timer.start(interval)
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent):
        """Emit when the title bar (not the hide button) is double-clicked."""
        if self._titlebar_click_excludes_hide_button(event):
            super().mouseDoubleClickEvent(event)
            return
        self._single_click_timer.stop()
        self.title_double_clicked.emit()
        event.accept()

class CombinedSidebarWidget(QWidget):
    """Combined widget containing tree view and preview with resizable sections"""
    
    # Signals
    tree_visibility_changed = Signal(bool)
    preview_visibility_changed = Signal(bool)
    widget_resized = Signal()
    
    def __init__(self, main_window, parent=None):
        super().__init__(parent)
        self.main_window = main_window
        self.tree_visible = True
        self.preview_visible = True
        self.tree_widget = None
        self.preview_widget = None
        
        # Store saved splitter sizes for session persistence
        # Format: [tree_size, preview_size] or None if not yet set
        self.saved_splitter_sizes = None
        self._adjusting_splitter = False

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
        
        # Add sections to splitter
        self.splitter.addWidget(self.tree_section)
        self.splitter.addWidget(self.preview_section)
        
        # Set initial sizes (tree / preview)
        self.splitter.setSizes([200, 200])
        
        # Connect splitter resize events
        self.splitter.splitterMoved.connect(self._on_splitter_moved)
        
        layout.addWidget(self.splitter)
        
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
            header.title_clicked.connect(self.main_window.focus_tree)
            header.title_double_clicked.connect(self._expand_tree_pane_to_fit)
        else:
            self.preview_header = header
            header.hide_button.clicked.connect(self._toggle_preview)
            header.title_double_clicked.connect(self._expand_preview_pane_to_fit)
        
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
        else:
            self.preview_content = content_area
            
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
        
    def _pane_visibility(self) -> list[bool]:
        return [self.tree_visible, self.preview_visible]

    def _header_height_for_pane(self, pane_idx: int) -> int:
        if pane_idx == 0 and self.tree_header:
            return self.tree_header.height()
        if pane_idx == 1 and self.preview_header:
            return self.preview_header.height()
        return 30

    def _pane_min_height(self, pane_idx: int, *, header_only: bool = False) -> int:
        if not self._pane_visibility()[pane_idx]:
            return 0
        return pane_min_height(
            self._header_height_for_pane(pane_idx), header_only=header_only
        )

    def _set_splitter_sizes_safe(self, sizes: list[int]) -> None:
        self._adjusting_splitter = True
        try:
            self.splitter.setSizes(sizes)
        finally:
            self._adjusting_splitter = False

    def _ensure_pane_headers_visible(
        self, collapse_header_only: dict[int, bool] | None = None
    ) -> bool:
        adjusted = ensure_pane_headers_visible(
            self.splitter,
            self._pane_visibility(),
            self._pane_min_height,
            collapse_header_only=collapse_header_only,
        )
        if adjusted is None:
            return False
        self._set_splitter_sizes_safe(adjusted)
        return True

    def _tree_view(self) -> QTreeView | None:
        handler = getattr(self.main_window, "file_tree_handler", None)
        if handler and handler.is_tree_initialized():
            tree = getattr(handler, "file_tree", None)
            if tree is not None:
                return tree
        if not self.tree_widget:
            return None
        views = self.tree_widget.findChildren(QTreeView)
        return views[0] if views else None

    def _tree_row_height(self, tree: QTreeView, index: QModelIndex | None = None) -> int:
        if index is not None and index.isValid():
            rect_h = tree.visualRect(index).height()
            if rect_h > 0:
                return rect_h
            hint = tree.sizeHintForRow(index.row())
            if hint > 0:
                return hint
        hint = tree.sizeHintForRow(0)
        if hint > 0:
            return hint
        return tree.fontMetrics().height() + 10

    def _tree_visible_rows_height(self, tree: QTreeView) -> int:
        model = tree.model()
        if model is None:
            return self._tree_row_height(tree) + tree.frameWidth() * 2
        if model.rowCount(QModelIndex()) == 0:
            return self._tree_row_height(tree) + tree.frameWidth() * 2

        total = 0
        index = model.index(0, 0, QModelIndex())
        while index.isValid():
            total += self._tree_row_height(tree, index)
            index = tree.indexBelow(index)
        return total + tree.frameWidth() * 2 + 2

    def _tree_panel_content_width(self) -> int:
        width = self.tree_content.width() if self.tree_content else 0
        if width <= 0:
            width = self.width()
        return max(width, 200)

    def _tree_widget_preferred_height(self, widget: QWidget, *, content_width: int) -> int:
        if widget is None or not widget.isVisible():
            return 0
        widget.adjustSize()
        if widget.height() > 0:
            return widget.height()

        handler = getattr(self.main_window, "file_tree_handler", None)
        label = getattr(handler, "current_dir_label", None) if handler else None
        if label is not None and (
            widget is label or widget is label.parentWidget()
        ):
            inner_w = content_width
            inner_layout = widget.layout() if widget is not label else None
            if inner_layout is not None:
                m = inner_layout.contentsMargins()
                inner_w = max(content_width - m.left() - m.right(), 50)
            label_h = label.heightForWidth(inner_w)
            if label_h > 0:
                total = label_h
                if inner_layout is not None:
                    m = inner_layout.contentsMargins()
                    total += m.top() + m.bottom()
                return total

        hint = widget.sizeHint().height()
        if hint > 0:
            return hint
        return widget.minimumSizeHint().height()

    def _tree_chrome_height(self) -> int:
        """Button bar, path label row, layout margins/spacing above the tree view."""
        chrome = 0
        handler = getattr(self.main_window, "file_tree_handler", None)
        tree = self._tree_view()
        content_w = self._tree_panel_content_width()
        if handler:
            ftw = handler.get_widget()
            if ftw is not None:
                layout = ftw.layout()
                if layout is not None:
                    m = layout.contentsMargins()
                    chrome += m.top() + m.bottom()
                    chrome_widgets = 0
                    for i in range(layout.count()):
                        item = layout.itemAt(i)
                        if item is None:
                            continue
                        w = item.widget()
                        if w is None or w is tree:
                            continue
                        chrome += self._tree_widget_preferred_height(
                            w, content_width=content_w
                        )
                        chrome_widgets += 1
                    if chrome_widgets > 1:
                        chrome += max(layout.spacing(), 0) * (chrome_widgets - 1)
        if self.tree_content and self.tree_content.layout():
            m = self.tree_content.layout().contentsMargins()
            chrome += m.top() + m.bottom()
        return chrome + 6

    def _tree_preferred_content_height(self) -> int:
        tree = self._tree_view()
        if tree is None:
            return MIN_PANE_CONTENT
        rows_h = self._tree_visible_rows_height(tree)
        return rows_h + self._tree_chrome_height()

    def _preview_client_width(self) -> int:
        width = self.preview_content.width() if self.preview_content else 0
        if width <= 0:
            width = self.width()
        return max(width, 1)

    def _needed_pane_height(self, pane_idx: int) -> int:
        header_h = self._header_height_for_pane(pane_idx)
        if pane_idx == 0:
            return header_h + self._tree_preferred_content_height()
        if pane_idx == 1 and self.preview_widget:
            return header_h + self.preview_widget.preferred_content_height(
                self._preview_client_width()
            )
        return header_h + MIN_PANE_CONTENT

    def _expand_pane_to_fit(self, pane_idx: int) -> None:
        """Resize one pane to fit its content; shrink neighbors only as needed."""
        if pane_idx == 0 and not self.tree_visible:
            self.set_tree_visible(True)
        elif pane_idx == 1 and not self.preview_visible:
            self.set_preview_visible(True)

        vis = self._pane_visibility()
        if not vis[pane_idx]:
            return

        needed = self._needed_pane_height(pane_idx)
        sizes = self.splitter.sizes()
        if pane_idx < len(sizes) and sizes[pane_idx] == needed:
            return

        total = max(self.height(), 1)
        collapse_flags = collapse_flags_for_target(
            pane_idx, needed, total, vis, self._pane_min_height
        )
        new_sizes = redistribute_for_target_pane(
            self.splitter,
            2,
            pane_idx,
            needed,
            vis,
            self._header_height_for_pane,
            self._pane_min_height,
            total,
            collapse_header_only=collapse_flags,
        )
        self._set_splitter_sizes_safe(new_sizes)
        self._ensure_pane_headers_visible(collapse_flags)
        self._persist_splitter_sizes()

    def _expand_tree_pane_to_fit(self) -> None:
        self._expand_pane_to_fit(0)

    def _expand_preview_pane_to_fit(self) -> None:
        self._expand_pane_to_fit(1)

    def _persist_splitter_sizes(self) -> None:
        """Merge current splitter sizes for visible panes into saved settings."""
        vis = self._pane_visibility()
        sizes = self.splitter.sizes()
        if len(sizes) != 2:
            return
        saved = (
            list(self.saved_splitter_sizes)
            if isinstance(self.saved_splitter_sizes, list) and len(self.saved_splitter_sizes) >= 2
            else [200, 200]
        )
        for i in range(2):
            if vis[i] and sizes[i] > 0:
                saved[i] = sizes[i]
        self.saved_splitter_sizes = saved

    def _update_splitter_sizes(self):
        """Update splitter sizes based on which panes are visible"""
        vis = self._pane_visibility()
        if not any(vis):
            return
        current_height = max(self.height(), 1)
        visible_indices = [i for i, v in enumerate(vis) if v]
        if len(visible_indices) == 1:
            sizes = [current_height if v else 0 for v in vis]
            self._set_splitter_sizes_safe(sizes)
            return

        saved = self.saved_splitter_sizes
        if saved and len(saved) >= 2:
            tree_saved = saved[0]
            preview_saved = saved[1] if len(saved) > 1 else saved[0]
            vis_saved = [
                tree_saved if vis[0] else 0,
                preview_saved if vis[1] else 0,
            ]
            total_saved = sum(vis_saved)
            if total_saved > 0:
                scaled = [
                    int(vis_saved[i] * current_height / total_saved) if vis[i] else 0
                    for i in range(2)
                ]
                total_scaled = sum(scaled)
                if total_scaled != current_height and visible_indices:
                    scaled[visible_indices[-1]] += current_height - total_scaled
                self._set_splitter_sizes_safe(scaled)
                self._ensure_pane_headers_visible()
                return

        each = current_height // len(visible_indices)
        sizes = [0, 0]
        for i in visible_indices:
            sizes[i] = each
        remainder = current_height - sum(sizes)
        if remainder and visible_indices:
            sizes[visible_indices[-1]] += remainder
        self._set_splitter_sizes_safe(sizes)
        self._ensure_pane_headers_visible()
    
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
        if not self._adjusting_splitter:
            self._ensure_pane_headers_visible()
        self._persist_splitter_sizes()
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
        
    def resizeEvent(self, event):
        """Handle resize events"""
        super().resizeEvent(event)
        new_h = event.size().height()
        if new_h > 0 and new_h != event.oldSize().height():
            self._update_splitter_sizes()
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
