#!/usr/bin/env python3
"""
Combined Sidebar Widget - Combines tree view and preview in a single resizable widget
"""

from PySide6.QtCore import Qt, QSize, Signal, QModelIndex, QTimer, QEvent, QPointF, QEventLoop
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
    MIN_PREVIEW_CONTENT_HEIGHT,
    apply_pane_titlebar_drag_delta,
    collapse_flags_for_target,
    ensure_pane_headers_visible,
    pane_height_at_target,
    pane_min_height,
    redistribute_for_target_pane,
)
from browser_window.sidebar.sidebar_pane_chrome import (
    apply_section_pane_shell,
    apply_sidebar_pane_background,
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
        self.tools_button = None
        self._header_layout = None
        self._single_click_timer = QTimer(self)
        self._single_click_timer.setSingleShot(True)
        self._single_click_timer.timeout.connect(self._emit_title_clicked)
        self._pane_resize_splitter = None
        self._pane_resize_idx: int | None = None
        self._pane_resize_min_h = None
        self._pane_resize_vis_fn = None
        self._pane_resize_on_drag_before = None
        self._pane_resize_on_drag_after = None
        self._pane_resize_press_global_y: float | None = None
        self._pane_resize_start_sizes: list[int] | None = None
        self._pane_resize_dragging = False
        self.setup_ui()
        
    def setup_ui(self):
        """Setup the header UI"""
        self.setFocusPolicy(Qt.NoFocus)
        self.setFixedHeight(30)
        layout = QHBoxLayout(self)
        self._header_layout = layout
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(8)
        
        self.title_label = QLabel(self.title)
        self.title_label.setFocusPolicy(Qt.NoFocus)
        self.title_label.installEventFilter(self)
        layout.addWidget(self.title_label)
        
        layout.addStretch()

        self.status_label = QLabel("")
        self.status_label.setFocusPolicy(Qt.NoFocus)
        self.status_label.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        self.status_label.hide()
        layout.addWidget(self.status_label)
        
        # Hide button
        self.hide_button = QPushButton("−")
        self.hide_button.setFixedSize(20, 20)
        self.hide_button.setFocusPolicy(Qt.NoFocus)
        layout.addWidget(self.hide_button)
        self.refresh_theme_styles()

    def set_tools_button(self, button: QPushButton | None) -> None:
        """Optional titlebar tools control (inserted before the hide button)."""
        layout = self._header_layout
        if layout is None:
            return
        if self.tools_button is not None:
            layout.removeWidget(self.tools_button)
            self.tools_button.setParent(None)
            self.tools_button = None
        if button is None:
            return
        button.setFixedSize(20, 20)
        button.setFocusPolicy(Qt.NoFocus)
        self.tools_button = button
        hide_idx = layout.indexOf(self.hide_button)
        if hide_idx < 0:
            layout.addWidget(button)
        else:
            layout.insertWidget(hide_idx, button)
        self.refresh_theme_styles()

    def _titlebar_chip_stylesheet(self) -> str:
        titlebar = QColor(tc.SIDEBAR_HEADER_BG_HEX)
        if not titlebar.isValid():
            titlebar = QColor("#2b2b2b")
        hb_bg = titlebar.lighter(200).name()
        hb_hover = titlebar.lighter(300).name()
        hb_pressed = titlebar.lighter(160).name()
        hb_border = titlebar.lighter(160).name()
        hb_border_hover = titlebar.lighter(180).name()
        return f"""
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
            QPushButton:disabled {{
                color: #888888;
            }}
        """

    def _style_titlebar_chip(self, button: QPushButton) -> None:
        button.setStyleSheet(self._titlebar_chip_stylesheet())

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
        self.status_label.setStyleSheet(f"""
            QLabel {{
                color: {tc.SIDEBAR_HEADER_TEXT_HEX};
                font-weight: bold;
                font-size: 12px;
                border-width: 0px;
            }}
        """)
        self._style_titlebar_chip(self.hide_button)
        if self.tools_button is not None:
            self._style_titlebar_chip(self.tools_button)

    def _titlebar_click_excludes_chrome_buttons(self, event: QMouseEvent) -> bool:
        pos = event.position().toPoint()
        for btn in (self.tools_button, self.hide_button):
            if btn is not None and btn.geometry().contains(pos):
                return True
        return False

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
            if isinstance(event, QMouseEvent):
                if et in (
                    QEvent.Type.MouseButtonPress,
                    QEvent.Type.MouseButtonDblClick,
                ):
                    mapped = self._map_title_label_mouse_event(event)
                    if et == QEvent.Type.MouseButtonDblClick:
                        self.mouseDoubleClickEvent(mapped)
                    else:
                        self.mousePressEvent(mapped)
                    return True
                if et == QEvent.Type.MouseMove:
                    mapped = self._map_title_label_mouse_event(event)
                    if self._handle_pane_resize_mouse_move(mapped):
                        return True
                if et == QEvent.Type.MouseButtonRelease:
                    mapped = self._map_title_label_mouse_event(event)
                    if self._handle_pane_resize_mouse_release(mapped):
                        return True
        return super().eventFilter(watched, event)

    def mousePressEvent(self, event: QMouseEvent):
        """Defer single-click so double-click on the title bar is not swallowed."""
        self._handle_pane_resize_mouse_press(event)
        if event.button() == Qt.LeftButton and not self._titlebar_click_excludes_chrome_buttons(event):
            app = QApplication.instance()
            interval = app.doubleClickInterval() if app else 400
            self._single_click_timer.start(interval)
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent):
        if self._handle_pane_resize_mouse_move(event):
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent):
        if self._handle_pane_resize_mouse_release(event):
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent):
        """Emit when the title bar (not the hide button) is double-clicked."""
        if self._titlebar_click_excludes_chrome_buttons(event):
            super().mouseDoubleClickEvent(event)
            return
        self._single_click_timer.stop()
        self._end_pane_resize_drag()
        self.title_double_clicked.emit()
        event.accept()

    def set_status_text(self, text: str) -> None:
        """Optional right-aligned status beside the hide button (e.g. job queue counts)."""
        text = (text or "").strip()
        self.status_label.setText(text)
        self.status_label.setVisible(bool(text))

    def set_title_suffix(self, suffix: str) -> None:
        """Append *suffix* to the base title (e.g. ' - HOLD')."""
        self.title_label.setText(f"{self.title}{suffix or ''}")

    def configure_pane_drag_resize(
        self,
        splitter,
        pane_idx: int,
        min_height_for_pane,
        vis_fn,
        *,
        on_drag_before=None,
        on_drag_after=None,
    ) -> None:
        """Drag this title bar up/down to resize *pane_idx* via the splitter above it."""
        if pane_idx < 1:
            return
        self._pane_resize_splitter = splitter
        self._pane_resize_idx = pane_idx
        self._pane_resize_min_h = min_height_for_pane
        self._pane_resize_vis_fn = vis_fn
        self._pane_resize_on_drag_before = on_drag_before
        self._pane_resize_on_drag_after = on_drag_after
        self.setMouseTracking(True)

    def _pane_resize_active(self) -> bool:
        return (
            self._pane_resize_splitter is not None
            and self._pane_resize_idx is not None
            and self._pane_resize_min_h is not None
            and self._pane_resize_vis_fn is not None
        )

    def _pane_resize_drag_threshold_exceeded(self, global_y: float) -> bool:
        if self._pane_resize_press_global_y is None:
            return False
        return abs(global_y - self._pane_resize_press_global_y) >= 3

    def _begin_pane_resize_drag(self, global_y: float) -> None:
        self._single_click_timer.stop()
        self._pane_resize_dragging = True
        self.setCursor(Qt.CursorShape.SizeVerCursor)
        self.grabMouse()
        self._pane_resize_start_sizes = list(self._pane_resize_splitter.sizes())

    def _apply_pane_resize_step(self, global_y: float) -> None:
        if (
            not self._pane_resize_dragging
            or self._pane_resize_press_global_y is None
            or self._pane_resize_start_sizes is None
        ):
            return
        total_dy = int(round(global_y - self._pane_resize_press_global_y))
        if total_dy == 0:
            return
        if self._pane_resize_on_drag_before:
            if self._pane_resize_on_drag_before(
                total_dy, self._pane_resize_start_sizes
            ):
                self._pane_resize_start_sizes = list(self._pane_resize_splitter.sizes())
                self._pane_resize_press_global_y = global_y
                total_dy = 0
        if total_dy != 0:
            apply_pane_titlebar_drag_delta(
                self._pane_resize_splitter,
                self._pane_resize_idx,
                total_dy,
                self._pane_resize_vis_fn(),
                self._pane_resize_min_h,
                start_sizes=self._pane_resize_start_sizes,
            )
        if self._pane_resize_on_drag_after:
            self._pane_resize_on_drag_after(total_dy)

    def _end_pane_resize_drag(self) -> None:
        if self._pane_resize_dragging:
            self._pane_resize_dragging = False
            self._pane_resize_start_sizes = None
            self.unsetCursor()
            if self.mouseGrabber() is self:
                self.releaseMouse()
        self._pane_resize_press_global_y = None

    def _handle_pane_resize_mouse_press(self, event: QMouseEvent) -> None:
        if (
            event.button() == Qt.MouseButton.LeftButton
            and self._pane_resize_active()
            and not self._titlebar_click_excludes_chrome_buttons(event)
        ):
            self._pane_resize_press_global_y = event.globalPosition().y()

    def _handle_pane_resize_mouse_move(self, event: QMouseEvent) -> bool:
        if not self._pane_resize_active() or self._pane_resize_press_global_y is None:
            return False
        global_y = event.globalPosition().y()
        if not self._pane_resize_dragging:
            if not self._pane_resize_drag_threshold_exceeded(global_y):
                return False
            self._begin_pane_resize_drag(global_y)
        self._apply_pane_resize_step(global_y)
        event.accept()
        return True

    def _handle_pane_resize_mouse_release(self, event: QMouseEvent) -> bool:
        if event.button() != Qt.MouseButton.LeftButton:
            return False
        was_dragging = self._pane_resize_dragging
        self._end_pane_resize_drag()
        return was_dragging

class CombinedSidebarWidget(QWidget):
    """Combined widget containing tree view and preview with resizable sections"""
    
    # Signals
    tree_visibility_changed = Signal(bool)
    preview_visibility_changed = Signal(bool)
    chat_visibility_changed = Signal(bool)
    chat_cover_changed = Signal(bool)
    widget_resized = Signal()
    
    def __init__(self, main_window, parent=None):
        super().__init__(parent)
        self.main_window = main_window
        self.tree_visible = True
        self.preview_visible = True
        self.tree_widget = None
        self.preview_widget = None

        try:
            settings = main_window.config.load_settings()
        except Exception:
            settings = {}
        try:
            from bundle_capabilities import chat_ui_enabled
            self._chat_feature_enabled = chat_ui_enabled()
        except ImportError:
            self._chat_feature_enabled = True
        self.chat_visible = (
            bool(settings.get('chat_visible', True))
            if self._chat_feature_enabled
            else False
        )
        self.chat_covers_panes = False
        self.chat_widget = None
        self.chat_section = None
        self.chat_header = None
        self.chat_content = None

        # Store saved splitter sizes for session persistence
        # Format: [tree_size, preview_size, chat_size] or None if not yet set
        self.saved_splitter_sizes = None
        self._adjusting_splitter = False
        self._pane_fit_targets: dict[int, int] = {}

        # Set focus policy to be in tab order
        # self.setFocusPolicy(Qt.StrongFocus)
        self.setFocusPolicy(Qt.NoFocus)
        
        self.setup_ui()
        
    def focusInEvent(self, event):
        """Handle focus in events - forward focus to tree view if displayed"""
        super().focusInEvent(event)
        if self.chat_covers_panes:
            mw = getattr(self, "main_window", None)
            if mw is not None and hasattr(mw, "focus_chat"):
                mw.focus_chat()
            return
        disp = self._display_pane_visibility()
        if disp[0] and self.tree_widget:
            self.tree_widget.setFocus()
        elif disp[1] and self.preview_widget:
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

        # Create chat section (bottom)
        self.chat_section = self._create_section("Chat", "chat")
        
        # Add sections to splitter
        self.splitter.addWidget(self.tree_section)
        self.splitter.addWidget(self.preview_section)
        self.splitter.addWidget(self.chat_section)
        if not self._chat_feature_enabled:
            self.chat_section.setVisible(False)
            self.chat_visible = False
        
        # Set initial sizes (tree / preview / chat)
        self.splitter.setSizes([200, 200, 200])

        self.chat_content.setVisible(self.chat_visible)
        self.chat_header.hide_button.setText("−" if self.chat_visible else "+")
        
        # Connect splitter resize events
        self.splitter.splitterMoved.connect(self._on_splitter_moved)
        
        layout.addWidget(self.splitter)
        if self.chat_visible and self._chat_feature_enabled:
            self._enter_chat_cover()
        else:
            self._apply_display_sections()
            self._update_splitter_sizes()
        
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
        th = get_active_theme()
        tree_shell = th.file_tree_pane_shell_stylesheet()
        if getattr(self, "tree_content", None):
            self.tree_content.setStyleSheet(tree_shell)
        pane_bg = th.sidebar_background_color_hex
        pane_ss = th.file_tree_pane_shell_stylesheet()
        for w in (
            getattr(self, "chat_section", None),
            getattr(self, "chat_content", None),
        ):
            if w is not None:
                apply_section_pane_shell(w, pane_bg, pane_ss)
        if getattr(self, "tree_header", None):
            self.tree_header.refresh_theme_styles()
        if getattr(self, "preview_header", None):
            self.preview_header.refresh_theme_styles()
        if getattr(self, "chat_header", None):
            self.chat_header.refresh_theme_styles()
        if getattr(self, "chat_widget", None) and hasattr(self.chat_widget, "refresh_theme_styles"):
            self.chat_widget.refresh_theme_styles()
        if getattr(self, "tree_widget", None):
            self._update_tree_header_focus(self.tree_widget.hasFocus())
        self._update_chat_header_focus(self._chat_pane_has_focus())

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
        elif section_type == "preview":
            self.preview_header = header
            header.hide_button.clicked.connect(self._toggle_preview)
            header.title_double_clicked.connect(self._expand_preview_pane_to_fit)
            header.configure_pane_drag_resize(
                self.splitter,
                1,
                self._pane_min_height,
                self._pane_visibility,
            )
        else:
            self.chat_header = header
            header.hide_button.clicked.connect(self._toggle_chat)
            header.title_double_clicked.connect(self._expand_chat_pane_to_fit)
            header.configure_pane_drag_resize(
                self.splitter,
                2,
                self._pane_min_height,
                self._pane_visibility,
            )
        
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
            self.chat_content = content_area
            content_area.setMinimumHeight(0)
            
        layout.addWidget(content_area)

        if section_type == "chat":
            _th = get_active_theme()
            pane_bg = _th.sidebar_background_color_hex
            pane_ss = _th.file_tree_pane_shell_stylesheet()
            for w in (section, content_area):
                apply_section_pane_shell(w, pane_bg, pane_ss)
        
        return section

    def set_chat_widget(self, chat_widget):
        """Set the chat widget in the chat section"""
        self.chat_widget = chat_widget
        if self.chat_widget:
            if self.chat_widget.parent():
                self.chat_widget.setParent(None)
            self.chat_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
            layout = self.chat_content.layout()
            container = getattr(self.main_window, "chat_container", None)
            if container is not None:
                if container.parent():
                    container.setParent(None)
                container.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
                container_layout = container.layout()
                if container_layout is None:
                    container_layout = QVBoxLayout(container)
                    container_layout.setContentsMargins(0, 0, 0, 0)
                    container_layout.setSpacing(0)
                if self.chat_widget.parent() is not container:
                    container_layout.addWidget(self.chat_widget)
                layout.addWidget(container)
            else:
                layout.addWidget(self.chat_widget)
            self.chat_widget.show()
            if hasattr(self.chat_widget, "attach_titlebar_tools"):
                self.chat_widget.attach_titlebar_tools()
            if hasattr(self.chat_widget, "ensure_input_focus_policy"):
                self.chat_widget.ensure_input_focus_policy()
            if hasattr(self.chat_widget, "refresh_theme_styles"):
                self.chat_widget.refresh_theme_styles()
            self._connect_chat_focus_events()
            self._update_chat_header_focus(self._chat_pane_has_focus())
        
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
        if self.chat_covers_panes:
            self.set_tree_visible(True)
        else:
            self.set_tree_visible(not self.tree_visible)

    def _toggle_preview(self):
        """Toggle preview visibility"""
        if self.chat_covers_panes:
            self.set_preview_visible(True)
        else:
            self.set_preview_visible(not self.preview_visible)

    def _toggle_chat(self):
        """Toggle chat visibility (also triggered by F9)"""
        self.set_chat_visible(not self.chat_visible)

    def is_chat_covering_panes(self) -> bool:
        return bool(self.chat_covers_panes)

    def enter_chat_cover(self) -> None:
        """Show chat only at full sidebar height (logical tree/preview unchanged)."""
        self._enter_chat_cover()

    def set_chat_covers_panes(self, covers: bool) -> None:
        if covers:
            self._enter_chat_cover()
        else:
            self._exit_chat_cover()

    def _logical_pane_visibility(self) -> list[bool]:
        chat_vis = self.chat_visible if self._chat_feature_enabled else False
        return [self.tree_visible, self.preview_visible, chat_vis]

    def _display_pane_visibility(self) -> list[bool]:
        if self.chat_covers_panes and self._chat_feature_enabled and self.chat_visible:
            return [False, False, True]
        return self._logical_pane_visibility()

    def _pane_visibility(self) -> list[bool]:
        return self._display_pane_visibility()

    def _apply_display_sections(self) -> None:
        disp = self._display_pane_visibility()
        if getattr(self, "tree_section", None):
            self.tree_section.setVisible(disp[0])
        if getattr(self, "preview_section", None):
            self.preview_section.setVisible(disp[1])
        if getattr(self, "chat_section", None) and self._chat_feature_enabled:
            self.chat_section.setVisible(disp[2])
        if getattr(self, "tree_content", None):
            self.tree_content.setVisible(self.tree_visible)
        if getattr(self, "preview_content", None):
            self.preview_content.setVisible(self.preview_visible)
        if getattr(self, "chat_content", None):
            self.chat_content.setVisible(self.chat_visible)
        if getattr(self, "tree_header", None):
            self.tree_header.hide_button.setText("−" if self.tree_visible else "+")
        if getattr(self, "preview_header", None):
            self.preview_header.hide_button.setText("−" if self.preview_visible else "+")
        if getattr(self, "chat_header", None):
            self.chat_header.hide_button.setText("−" if self.chat_visible else "+")

    def _notify_cover_changed(self) -> None:
        self.chat_cover_changed.emit(self.chat_covers_panes)
        mw = getattr(self, "main_window", None)
        if mw is not None and hasattr(mw, "_sync_left_sidebar_tab_order"):
            mw._sync_left_sidebar_tab_order()

    def _enter_chat_cover(self) -> None:
        if not self._chat_feature_enabled or not self.chat_visible:
            return
        was_covering = self.chat_covers_panes
        self.chat_covers_panes = True
        self._apply_display_sections()
        self._update_splitter_sizes()
        if not was_covering:
            self._notify_cover_changed()

    def _exit_chat_cover(self) -> None:
        if not self.chat_covers_panes:
            return
        self.chat_covers_panes = False
        self._apply_display_sections()
        self._update_splitter_sizes()
        self._notify_cover_changed()

    def _maybe_reenter_chat_cover(self) -> None:
        if (
            self._chat_feature_enabled
            and self.chat_visible
            and not self.tree_visible
            and not self.preview_visible
        ):
            self._enter_chat_cover()

    def _header_height_for_pane(self, pane_idx: int) -> int:
        if pane_idx == 0 and self.tree_header:
            return self.tree_header.height()
        if pane_idx == 1 and self.preview_header:
            return self.preview_header.height()
        if pane_idx == 2 and self.chat_header:
            return self.chat_header.height()
        return 30

    def _pane_min_height(self, pane_idx: int, *, header_only: bool = False) -> int:
        if not self._pane_visibility()[pane_idx]:
            return 0
        header_h = self._header_height_for_pane(pane_idx)
        if header_only:
            return header_h
        if pane_idx == 1:
            return header_h + MIN_PREVIEW_CONTENT_HEIGHT
        return pane_min_height(header_h, header_only=False)

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

    def _prepare_pane_measure(self, pane_idx: int) -> None:
        if pane_idx == 0:
            tree = self._tree_view()
            if tree is not None:
                tree.updateGeometry()
        if pane_idx == 1 and self.preview_widget is not None:
            self.preview_widget.updateGeometry()
        if pane_idx == 2 and self.chat_widget is not None:
            self.chat_widget.updateGeometry()
        QApplication.processEvents(QEventLoop.ProcessEventsFlag.ExcludeUserInputEvents)

    def _pane_size_at_fit_target(self, pane_idx: int, current: int, needed: int) -> bool:
        return pane_height_at_target(
            current,
            needed,
            stored_target=self._pane_fit_targets.get(pane_idx),
        )

    def _resize_pane_to_height(self, pane_idx: int, target_height: int) -> None:
        vis = self._pane_visibility()
        if not vis[pane_idx]:
            return
        total = max(self.height(), 1)
        collapse_flags = collapse_flags_for_target(
            pane_idx, target_height, total, vis, self._pane_min_height
        )
        new_sizes = redistribute_for_target_pane(
            self.splitter,
            3,
            pane_idx,
            target_height,
            vis,
            self._header_height_for_pane,
            self._pane_min_height,
            total,
            collapse_header_only=collapse_flags,
        )
        self._set_splitter_sizes_safe(new_sizes)
        self._ensure_pane_headers_visible(collapse_flags)
        self._persist_splitter_sizes()

    def _collapse_pane_from_fit(self, pane_idx: int) -> None:
        self._resize_pane_to_height(pane_idx, self._pane_min_height(pane_idx))

    def _expand_pane_to_fit_stabilized(self, pane_idx: int) -> None:
        vis = self._pane_visibility()
        if not vis[pane_idx]:
            return

        prev_needed = -1
        prev_current = -1
        for _ in range(4):
            self._prepare_pane_measure(pane_idx)
            needed = self._needed_pane_height(pane_idx)
            sizes = self.splitter.sizes()
            current = sizes[pane_idx] if pane_idx < len(sizes) else 0

            if prev_needed >= 0 and abs(needed - prev_needed) <= 1 and current == prev_current:
                break

            self._resize_pane_to_height(pane_idx, needed)
            prev_needed = needed
            prev_current = self.splitter.sizes()[pane_idx]

        self._pane_fit_targets[pane_idx] = self.splitter.sizes()[pane_idx]

    def _toggle_pane_fit(self, pane_idx: int) -> None:
        if pane_idx == 0 and not self.tree_visible:
            self.set_tree_visible(True)
        elif pane_idx == 1 and not self.preview_visible:
            self.set_preview_visible(True)
        elif pane_idx == 2 and not self.chat_visible:
            self.set_chat_visible(True)

        vis = self._pane_visibility()
        if not vis[pane_idx]:
            return

        self._prepare_pane_measure(pane_idx)
        needed = self._needed_pane_height(pane_idx)
        sizes = self.splitter.sizes()
        current = sizes[pane_idx] if pane_idx < len(sizes) else 0

        if self._pane_size_at_fit_target(pane_idx, current, needed):
            self._collapse_pane_from_fit(pane_idx)
            self._pane_fit_targets.pop(pane_idx, None)
        else:
            self._expand_pane_to_fit_stabilized(pane_idx)

    def _needed_pane_height(self, pane_idx: int) -> int:
        header_h = self._header_height_for_pane(pane_idx)
        if pane_idx == 0:
            return header_h + self._tree_preferred_content_height()
        if pane_idx == 1 and self.preview_widget:
            return header_h + self.preview_widget.preferred_content_height(
                self._preview_client_width()
            )
        if pane_idx == 2 and self.chat_widget:
            return header_h + self.chat_widget.preferred_content_height()
        return header_h + MIN_PANE_CONTENT

    def _expand_tree_pane_to_fit(self) -> None:
        self._toggle_pane_fit(0)

    def _expand_preview_pane_to_fit(self) -> None:
        self._toggle_pane_fit(1)

    def _expand_chat_pane_to_fit(self) -> None:
        if self.chat_covers_panes:
            return
        self._toggle_pane_fit(2)

    def _persist_splitter_sizes(self) -> None:
        """Merge current splitter sizes for displayed panes into saved settings."""
        vis = self._display_pane_visibility()
        sizes = self.splitter.sizes()
        if len(sizes) != 3:
            return
        saved = (
            list(self.saved_splitter_sizes)
            if isinstance(self.saved_splitter_sizes, list) and len(self.saved_splitter_sizes) == 3
            else [200, 200, 200]
        )
        for i in range(3):
            if vis[i] and sizes[i] > 0:
                saved[i] = sizes[i]
        self.saved_splitter_sizes = saved

    def _update_splitter_sizes(self):
        """Update splitter sizes based on which panes are displayed. Order: [tree, preview, chat]."""
        vis = self._display_pane_visibility()
        if not any(vis):
            return
        current_height = max(self.height(), 1)
        visible_indices = [i for i, v in enumerate(vis) if v]
        if len(visible_indices) == 1:
            sizes = [current_height if v else 0 for v in vis]
            self._set_splitter_sizes_safe(sizes)
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
                self._set_splitter_sizes_safe(scaled)
                self._ensure_pane_headers_visible()
                return

        each = current_height // len(visible_indices)
        sizes = [0, 0, 0]
        for i in visible_indices:
            sizes[i] = each
        remainder = current_height - sum(sizes)
        if remainder and visible_indices:
            sizes[visible_indices[-1]] += remainder
        self._set_splitter_sizes_safe(sizes)
        self._ensure_pane_headers_visible()
    
    def _update_overall_visibility(self):
        """Update overall widget visibility based on section visibility"""
        if not any(self._logical_pane_visibility()):
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
            self._pane_fit_targets.clear()
            self._ensure_pane_headers_visible()
        self._persist_splitter_sizes()
        self.widget_resized.emit()
        
    def set_tree_visible(self, visible):
        """Set tree visibility programmatically (logical; may exit chat cover)."""
        if visible and self.chat_covers_panes:
            self._exit_chat_cover()

        if self.tree_visible != visible:
            self.tree_visible = visible
            self._apply_display_sections()
            self._update_splitter_sizes()
            self.tree_visibility_changed.emit(visible)
            self._update_overall_visibility()
        elif visible and self.tree_widget:
            self.tree_widget.show()

        if not visible:
            self._maybe_reenter_chat_cover()

    def set_preview_visible(self, visible):
        """Set preview visibility programmatically (logical; may exit chat cover)."""
        if visible and self.chat_covers_panes:
            self._exit_chat_cover()

        if self.preview_visible != visible:
            self.preview_visible = visible
            self._apply_display_sections()
            self._update_splitter_sizes()
            self.preview_visibility_changed.emit(visible)
            self._update_overall_visibility()

        if not visible:
            self._maybe_reenter_chat_cover()

    def set_chat_visible(self, visible, *, enter_cover: bool | None = None):
        """Set chat visibility programmatically (e.g. from F9).

        enter_cover: when showing chat, True forces cover mode, False leaves multi-pane layout,
        None defaults to entering cover mode.
        """
        if not self._chat_feature_enabled:
            return
        if self.chat_visible != visible:
            self.chat_visible = visible
            if visible:
                if enter_cover is False:
                    self.chat_covers_panes = False
                    self._apply_display_sections()
                else:
                    self._enter_chat_cover()
            else:
                self.chat_covers_panes = False
                self._apply_display_sections()
            self.chat_header.hide_button.setText("−" if visible else "+")
            if visible and self.chat_widget and hasattr(self.chat_widget, "on_pane_activated"):
                self.chat_widget.on_pane_activated()
            self._update_splitter_sizes()
            self.main_window.config.update_setting('chat_visible', visible)
            self.main_window.chat_visible = visible
            self._sync_chat_menu_action()
            self._update_overall_visibility()
            self.chat_visibility_changed.emit(visible)
            self.widget_resized.emit()
            self._update_chat_header_focus(self._chat_pane_has_focus())
            if not visible:
                self._notify_cover_changed()
        elif visible and self.chat_widget:
            if enter_cover is False:
                if self.chat_covers_panes:
                    self._exit_chat_cover()
            else:
                self._enter_chat_cover()
            self.chat_widget.show()
            if hasattr(self.chat_widget, "on_pane_activated"):
                self.chat_widget.on_pane_activated()
            if hasattr(self.chat_widget, "ensure_input_focus_policy"):
                self.chat_widget.ensure_input_focus_policy()
            self._update_overall_visibility()
            self.chat_visibility_changed.emit(visible)
            self._update_chat_header_focus(self._chat_pane_has_focus())

    def _sync_chat_menu_action(self) -> None:
        action = getattr(self.main_window, "toggle_chat_action", None)
        if action is not None:
            action.setChecked(self.chat_visible)
            action.setText("Hide Chat" if self.chat_visible else "Show Chat")

    def is_chat_visible(self):
        """Check if chat is visible"""
        if not self._chat_feature_enabled:
            return False
        return self.chat_visible

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
    
    def _connect_chat_focus_events(self):
        """Track focus anywhere in the chat pane to highlight its header."""
        if getattr(self, "_chat_focus_connected", False):
            return
        app = QApplication.instance()
        if app is None:
            return
        app.focusChanged.connect(self._on_application_focus_changed)
        self._chat_focus_connected = True

    def _on_application_focus_changed(self, _old, new) -> None:
        self._update_chat_header_focus(self._chat_pane_has_focus(new))

    def _chat_pane_has_focus(self, focus_widget=None) -> bool:
        if not self._chat_feature_enabled or not self.is_chat_visible():
            return False
        chat = getattr(self, "chat_widget", None)
        if chat is None or not chat.isVisible():
            return False
        if focus_widget is None:
            app = QApplication.instance()
            focus_widget = app.focusWidget() if app is not None else None
        if focus_widget is None:
            return False
        return focus_widget is chat or chat.isAncestorOf(focus_widget)
    
    def _update_tree_header_focus(self, has_focus):
        """Update the tree header background color to indicate focus state"""
        if getattr(self, 'tree_header', None):
            bg_color = tc.TREE_HEADER_FOCUS_BG_HEX if has_focus else tc.SIDEBAR_HEADER_BG_HEX
            self.tree_header.setStyleSheet(self.tree_header._qframe_stylesheet(bg_color))

    def _update_chat_header_focus(self, has_focus):
        """Update the chat header background color to indicate focus state"""
        if getattr(self, "chat_header", None):
            bg_color = tc.TREE_HEADER_FOCUS_BG_HEX if has_focus else tc.SIDEBAR_HEADER_BG_HEX
            self.chat_header.setStyleSheet(self.chat_header._qframe_stylesheet(bg_color))
