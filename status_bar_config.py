#!/usr/bin/env python3
"""
Status Bar Configuration and Management
Provides a flexible layout system for the status bar with configurable sections
"""

from typing import Dict, List, Tuple, Optional
import os
import logging
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QWidget,
    QStatusBar,
    QProgressBar,
    QMenu,
    QWidgetAction,
    QTextBrowser,
    QVBoxLayout,
)
from PySide6.QtCore import Qt, QPoint, QTimer, QUrl
from PySide6.QtGui import QMouseEvent, QKeySequence, QAction
from theme_service import get_active_theme


def _status_bar_fg_hex() -> str:
    return get_active_theme().status_bar_label_text_hex


def _status_bar_disabled_hex() -> str:
    return get_active_theme().status_bar_label_disabled_hex


def _status_bar_popup_menu_stylesheet() -> str:
    """Context menus on status bar sections — matches active theme."""
    from theme_service import get_active_theme

    return get_active_theme().status_bar_context_menu_stylesheet()


def _task_info_browser_stylesheet(*, job_queue_cell: bool = False) -> str:
    t = get_active_theme()
    bg = t.default_background_color_hex if job_queue_cell else "transparent"
    return f"""
        QTextBrowser {{
            color: {t.text_color_hex};
            background-color: {bg};
            padding: 6px 18px 8px 18px;
            font-size: 12px;
            border: none;
        }}
    """


def _status_bar_task_info_label_stylesheet() -> str:
    return _task_info_browser_stylesheet(job_queue_cell=False)


def configure_task_info_text_browser(
    browser: QTextBrowser,
    main_window,
    *,
    job_queue_cell: bool = False,
    max_width: int | None = None,
    fixed_width: int | None = None,
) -> None:
    """Shared setup for status-bar menu and job-queue info cells (incl. reflevel:// links)."""
    browser.setReadOnly(True)
    browser.setOpenExternalLinks(False)
    browser.setOpenLinks(False)
    browser.setFrameShape(QTextBrowser.Shape.NoFrame)
    browser.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    browser.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    browser.setStyleSheet(_task_info_browser_stylesheet(job_queue_cell=job_queue_cell))
    if max_width is not None:
        browser.setMaximumWidth(max_width)
    if fixed_width is not None:
        browser.setFixedWidth(fixed_width)
    browser.anchorClicked.connect(
        lambda url: handle_task_info_reference_link_clicked(main_window, url)
    )


def handle_task_info_reference_link_clicked(main_window, url: QUrl) -> None:
    if not main_window:
        return
    url_str = url.toString()
    if url_str == "skipcooldown://":
        try:
            from imagegen_plugins.image_gen_controller import get_imagegen_controller

            get_imagegen_controller(main_window).skip_copy_cooldown()
        except ImportError:
            pass
        return
    if url_str != "reflevel://":
        return
    try:
        from imagegen_plugins.image_gen_controller import get_imagegen_controller

        controller = get_imagegen_controller(main_window)
        paths = controller.get_task_reference_paths()
        if paths:
            controller.open_task_reference_paths(paths)
    except ImportError:
        pass


def _wrap_task_info_html(body_html: str) -> str:
    from theme_service import get_active_theme

    t = get_active_theme()
    return (
        f'<html><body style="color:{t.text_color_hex}; font-size:12px; '
        f'margin:0; padding:0;">{body_html}</body></html>'
    )


def _apply_task_info_html_to_browser(
    info_browser: QTextBrowser,
    body_html: str,
    *,
    content_width: int | None = None,
) -> int:
    """Set task-info HTML on the browser and resize to fit content; returns height."""
    if content_width is not None:
        info_browser.setFixedWidth(content_width)
    try:
        from imagegen_plugins.job_prompt_tooltip import (
            notify_job_prompt_tooltip_content_updating,
        )

        notify_job_prompt_tooltip_content_updating(info_browser)
    except ImportError:
        pass
    info_browser.setHtml(_wrap_task_info_html(body_html))
    info_browser.document().setDocumentMargin(0)
    text_width = max(200, info_browser.width() - 36)
    info_browser.document().setTextWidth(text_width)
    doc_height = info_browser.document().size().height()
    layout_height = info_browser.document().documentLayout().documentSize().height()
    content_h = max(doc_height, layout_height)
    if content_h < 20:
        line_h = info_browser.fontMetrics().lineSpacing()
        blocks = max(1, info_browser.document().blockCount())
        content_h = line_h * blocks
    fixed_h = int(min(max(content_h, 48) + 16, 420))
    info_browser.setFixedHeight(fixed_h)
    info_browser.setMinimumHeight(fixed_h)
    return fixed_h


def _progressive_images_row_widget(main_window, parent: QWidget) -> Optional[QWidget]:
    """Table-style row for toggling show_progressive_images on supported pipelines."""
    try:
        from imagegen_plugins.image_gen_controller import get_imagegen_controller
    except ImportError:
        return None
    state = get_imagegen_controller(main_window).get_show_progressive_images_menu_state()
    if state is None:
        return None
    _supported, enabled = state
    t = get_active_theme()
    row = QWidget(parent)
    layout = QHBoxLayout(row)
    layout.setContentsMargins(18, 0, 18, 8)
    layout.setSpacing(8)
    label = QLabel("<b>Inter</b>", row)
    label.setStyleSheet(f"color: {t.text_color_hex}; font-size: 12px;")
    checkbox = QCheckBox("Show intermediate images", row)
    checkbox.setChecked(enabled)
    checkbox.setStyleSheet(
        f"color: {t.text_color_hex}; font-size: 12px; spacing: 6px;"
    )

    def _on_toggled(checked: bool) -> None:
        get_imagegen_controller(main_window).set_show_progressive_images(checked)

    checkbox.toggled.connect(_on_toggled)
    layout.addWidget(label, 0, Qt.AlignmentFlag.AlignLeft)
    layout.addWidget(checkbox, 1, Qt.AlignmentFlag.AlignLeft)
    return row


# Set up logging for status bar operations

class ClickableFilterLabel(QLabel):
    """A clickable QLabel for the filter section that shows a context menu with filter options"""
    
    def __init__(self, text="", parent=None):
        super().__init__(text, parent)
        self.main_window = None
        # Cursor will be updated based on view mode
        self._update_cursor()
    
    def set_main_window(self, main_window):
        """Set the main window reference for creating context menu"""
        self.main_window = main_window
        self._update_cursor()
    
    def _update_cursor(self):
        """Update cursor based on view mode and specific files mode"""
        if (self.main_window and 
            getattr(self.main_window, 'current_view_mode', '') in ('thumbnail', 'list') and
            not getattr(self.main_window, 'specific_files_active', False)):
            self.setCursor(Qt.PointingHandCursor)
        else:
            self.setCursor(Qt.ArrowCursor)
    
    def mousePressEvent(self, event: QMouseEvent):
        """Handle mouse clicks to show filter context menu"""
        # Allow clicks when in thumbnail or list mode and not in specific files mode
        if (event.button() in (Qt.LeftButton, Qt.RightButton) and 
            self.main_window and 
            getattr(self.main_window, 'current_view_mode', '') in ('thumbnail', 'list') and
            not getattr(self.main_window, 'specific_files_active', False)):
            self._show_filter_menu()
        super().mousePressEvent(event)
    
    def _show_filter_menu(self):
        """Show context menu with filter options above the filter section"""
        if not self.main_window:
            return
        
        # Create context menu with same styling as status bar
        menu = QMenu(self)
        menu.setStyleSheet(_status_bar_popup_menu_stylesheet())
        
        # Get saved filters and current filter
        from config import get_config
        config = get_config()
        saved_filters = config.get_saved_filters()
        current_filter = getattr(self.main_window, 'filter_pattern', None)
        
        # Normalize current filter for comparison (remove trailing *)
        current_filter_normalized = None
        if current_filter:
            # Remove trailing * for comparison
            if current_filter.endswith('*'):
                current_filter_normalized = current_filter[:-1]
            else:
                current_filter_normalized = current_filter
            # Handle '*' case
            if current_filter_normalized == '':
                current_filter_normalized = '*'
        
        # Collect all filters to show (saved filters + current if different)
        filters_to_show = []
        seen = set()
        
        # Add current filter if it's not '*' and not already in saved filters
        if current_filter_normalized and current_filter_normalized != '*':
            # Check if it's already in saved filters
            in_saved = False
            for saved in saved_filters:
                saved_normalized = saved
                if saved_normalized.endswith('*'):
                    saved_normalized = saved_normalized[:-1]
                if saved_normalized == current_filter_normalized:
                    in_saved = True
                    break
            if not in_saved:
                filters_to_show.append(current_filter_normalized)
                seen.add(current_filter_normalized)
        
        # Add saved filters
        for pattern in saved_filters:
            pattern_normalized = pattern
            if pattern_normalized.endswith('*'):
                pattern_normalized = pattern_normalized[:-1]
            if pattern_normalized and pattern_normalized not in seen:
                filters_to_show.append(pattern_normalized)
                seen.add(pattern_normalized)
        
        # Add "Edit..." action at the top
        edit_action = QAction("Edit...", menu)
        edit_action.triggered.connect(self._show_filter_dialog)
        menu.addAction(edit_action)
        
        menu.addSeparator()
        
        # Add "No filter (*)" action
        no_filter_action = QAction("No Filter (*)", menu)
        no_filter_action.triggered.connect(lambda: self._apply_filter('*'))
        # Mark as checked if current filter is '*' or None/empty
        if not current_filter or current_filter == '*' or current_filter_normalized == '*':
            no_filter_action.setCheckable(True)
            no_filter_action.setChecked(True)
        menu.addAction(no_filter_action)
        
        # Add separator before saved filter presets
        if filters_to_show:
            menu.addSeparator()
        
        # Add filter actions
        for pattern in filters_to_show:
            # Display pattern with * if it doesn't have wildcards
            display_pattern = pattern
            if '*' not in pattern and '?' not in pattern and '[' not in pattern:
                display_pattern = pattern + '*'
            
            filter_action = QAction(display_pattern, menu)
            filter_action.triggered.connect(lambda checked, p=pattern: self._apply_filter(p))
            # Mark current filter as checked
            if pattern == current_filter_normalized:
                filter_action.setCheckable(True)
                filter_action.setChecked(True)
            menu.addAction(filter_action)
        
        # Calculate position: above the widget, aligned to left edge
        # Get widget's bottom-left corner in global coordinates
        widget_bottom_left = self.mapToGlobal(QPoint(0, self.height()))
        # Position menu above the widget (subtract status bar height)
        menu_height = menu.sizeHint().height() + self.height()  # Use status bar widget height as margin
        menu_pos = QPoint(widget_bottom_left.x(), widget_bottom_left.y() - menu_height - 4) # sub 4 to acct for border
        
        # Show menu at calculated position
        menu.exec(menu_pos)
    
    def _apply_filter(self, pattern: str):
        """Apply a filter pattern to the main window"""
        if not self.main_window:
            return
        
        # Normalize pattern (add trailing * if needed)
        from config import get_config, ImageBrowserConfig
        config = get_config()
        
        if pattern == '*':
            normalized_pattern = '*'
        else:
            normalized_pattern = ImageBrowserConfig.normalize_filter_pattern(pattern)
        
        # Apply filter
        if hasattr(self.main_window, 'filter_pattern'):
            self.main_window.filter_pattern = normalized_pattern
            # Update setting
            config.update_setting('filter_pattern', normalized_pattern)
            # Update status bar immediately to reflect filter change
            if hasattr(self.main_window, 'status_bar_manager'):
                self.main_window.status_bar_manager._update_filter_section(self.main_window)
            # Refresh directory to apply filter
            if hasattr(self.main_window, 'refresh_directory'):
                self.main_window.refresh_directory()
    
    def _show_filter_dialog(self):
        """Show the filter editing dialog"""
        if not self.main_window:
            return
        
        from config import get_config
        from filter_dialog import FilterDialog
        
        config = get_config()
        saved_filters = config.get_saved_filters()
        
        # Get current filter pattern
        current_filter = None
        if hasattr(self.main_window, 'filter_pattern') and self.main_window.filter_pattern:
            current_filter = self.main_window.filter_pattern
        
        # Show dialog
        edited_filters = FilterDialog.edit_filters(saved_filters, self.main_window, current_filter)
        
        if edited_filters is not None:
            # Save the edited filters
            config.save_filters(edited_filters)

class ClickableSortLabel(QLabel):
    """A clickable QLabel for the sort section that shows a context menu with sort options"""
    
    def __init__(self, text="", parent=None):
        super().__init__(text, parent)
        self.main_window = None
        # Enable mouse tracking to show pointer cursor on hover
        self.setCursor(Qt.PointingHandCursor)
    
    def set_main_window(self, main_window):
        """Set the main window reference for creating context menu"""
        self.main_window = main_window
    
    def mousePressEvent(self, event: QMouseEvent):
        """Handle mouse clicks to show sort context menu"""
        if event.button() in (Qt.LeftButton, Qt.RightButton) and self.main_window:
            self._show_sort_menu()
        super().mousePressEvent(event)
    
    def _show_sort_menu(self):
        """Show context menu with sort options above the sort section"""
        if not self.main_window:
            return
        
        # Create context menu with same styling as status bar
        menu = QMenu(self)
        menu.setStyleSheet(_status_bar_popup_menu_stylesheet())
        
        # Add sort actions - Similar to View>Sort submenu
        # Create new actions that trigger the same slots to avoid Qt's action movement behavior
        # Sort by Date - Newest first
        if hasattr(self.main_window, 'set_date_sort'):
            date_action_newest = QAction("Date ↑ (Newest First)", menu)
            date_action_newest.setShortcut(QKeySequence("D"))
            date_action_newest.setCheckable(True)
            date_action_newest.triggered.connect(lambda: self.main_window.set_date_sort(reverse=False))
            # Sync checked state with menu action if it exists
            if hasattr(self.main_window, 'date_sort_action'):
                date_action_newest.setChecked(self.main_window.date_sort_action.isChecked())
            menu.addAction(date_action_newest)
        
        # Sort by Date - Oldest first
        if hasattr(self.main_window, 'set_date_sort'):
            date_action_oldest = QAction("Date ↓ (Oldest First)", menu)
            date_action_oldest.setShortcut(QKeySequence("Shift+D"))
            date_action_oldest.setCheckable(True)
            date_action_oldest.triggered.connect(lambda: self.main_window.set_date_sort(reverse=True))
            # Sync checked state with menu action if it exists
            if hasattr(self.main_window, 'date_sort_newest_action'):
                date_action_oldest.setChecked(self.main_window.date_sort_newest_action.isChecked())
            menu.addAction(date_action_oldest)
        
        
        # Sort by EXIF Date month - Newest first
        if hasattr(self.main_window, 'set_exif_date_sort'):
            exif_date_action_newest = QAction("EXIF Month ↑ (Newest First)", menu)
            exif_date_action_newest.setShortcut(QKeySequence("X"))
            exif_date_action_newest.setCheckable(True)
            exif_date_action_newest.triggered.connect(lambda: self.main_window.set_exif_date_sort(reverse=False))
            # Sync checked state with menu action if it exists
            if hasattr(self.main_window, 'exif_date_sort_action'):
                exif_date_action_newest.setChecked(self.main_window.exif_date_sort_action.isChecked())
            menu.addAction(exif_date_action_newest)
        
        # Sort by EXIF Date month - Oldest first
        if hasattr(self.main_window, 'set_exif_date_sort'):
            exif_date_action_oldest = QAction("EXIF Month ↓ (Oldest First)", menu)
            exif_date_action_oldest.setShortcut(QKeySequence("Shift+X"))
            exif_date_action_oldest.setCheckable(True)
            exif_date_action_oldest.triggered.connect(lambda: self.main_window.set_exif_date_sort(reverse=True))
            # Sync checked state with menu action if it exists
            if hasattr(self.main_window, 'exif_date_sort_reverse_action'):
                exif_date_action_oldest.setChecked(self.main_window.exif_date_sort_reverse_action.isChecked())
            menu.addAction(exif_date_action_oldest)

        # Sort by EXIF Date year - Newest first
        if hasattr(self.main_window, 'set_exif_year_sort'):
            exif_year_action_newest = QAction("EXIF Year ↑ (Newest First)", menu)
            exif_year_action_newest.setShortcut(QKeySequence("Y"))
            exif_year_action_newest.setCheckable(True)
            exif_year_action_newest.triggered.connect(lambda: self.main_window.set_exif_year_sort(reverse=False))
            # Sync checked state with menu action if it exists
            if hasattr(self.main_window, 'exif_year_sort_action'):
                exif_year_action_newest.setChecked(self.main_window.exif_year_sort_action.isChecked())
            menu.addAction(exif_year_action_newest)
        
        # Sort by EXIF Date year - Oldest first
        if hasattr(self.main_window, 'set_exif_year_sort'):
            exif_year_action_oldest = QAction("EXIF Year ↓ (Oldest First)", menu)
            exif_year_action_oldest.setShortcut(QKeySequence("Shift+Y"))
            exif_year_action_oldest.setCheckable(True)
            exif_year_action_oldest.triggered.connect(lambda: self.main_window.set_exif_year_sort(reverse=True))
            # Sync checked state with menu action if it exists
            if hasattr(self.main_window, 'exif_year_sort_reverse_action'):
                exif_year_action_oldest.setChecked(self.main_window.exif_year_sort_reverse_action.isChecked())
            menu.addAction(exif_year_action_oldest)
        
        # Sort by Name - A-Z
        if hasattr(self.main_window, 'set_name_sort'):
            name_action_az = QAction("Name ↑ (A-Z)", menu)  # Added up arrow
            name_action_az.setShortcut(QKeySequence("N"))
            name_action_az.setCheckable(True)
            name_action_az.triggered.connect(lambda: self.main_window.set_name_sort(reverse=False))
            # Sync checked state with menu action if it exists
            if hasattr(self.main_window, 'name_sort_action'):
                name_action_az.setChecked(self.main_window.name_sort_action.isChecked())
            menu.addAction(name_action_az)
        
        # Sort by Name - Z-A
        if hasattr(self.main_window, 'set_name_sort'):
            name_action_za = QAction("Name ↓ (Z-A)", menu)
            name_action_za.setShortcut(QKeySequence("Shift+N"))
            name_action_za.setCheckable(True)
            name_action_za.triggered.connect(lambda: self.main_window.set_name_sort(reverse=True))
            # Sync checked state with menu action if it exists
            if hasattr(self.main_window, 'name_sort_reverse_action'):
                name_action_za.setChecked(self.main_window.name_sort_reverse_action.isChecked())
            menu.addAction(name_action_za)
        
        # Sort by Size - Largest first
        if hasattr(self.main_window, 'set_size_sort'):
            size_action_largest = QAction("Size ↑ (Largest First)", menu)
            size_action_largest.setShortcut(QKeySequence("Z"))
            size_action_largest.setCheckable(True)
            size_action_largest.triggered.connect(lambda: self.main_window.set_size_sort(reverse=False))
            # Sync checked state with menu action if it exists
            if hasattr(self.main_window, 'size_sort_action'):
                size_action_largest.setChecked(self.main_window.size_sort_action.isChecked())
            menu.addAction(size_action_largest)
        
        # Sort by Size - Smallest first
        if hasattr(self.main_window, 'set_size_sort'):
            size_action_smallest = QAction("Size ↓ (Smallest First)", menu)
            size_action_smallest.setShortcut(QKeySequence("Shift+Z"))
            size_action_smallest.setCheckable(True)
            size_action_smallest.triggered.connect(lambda: self.main_window.set_size_sort(reverse=True))
            # Sync checked state with menu action if it exists
            if hasattr(self.main_window, 'size_sort_reverse_action'):
                size_action_smallest.setChecked(self.main_window.size_sort_reverse_action.isChecked())
            menu.addAction(size_action_smallest)
        
        # Reverse Order
        if hasattr(self.main_window, 'simple_reverse_image_order'):
            reverse_action = QAction("Reverse Sort Order", menu)
            reverse_action.setShortcut(QKeySequence("Ctrl+T"))
            reverse_action.triggered.connect(self.main_window.simple_reverse_image_order)
            menu.addAction(reverse_action)
        
        # Random Order
        if hasattr(self.main_window, 'view_mode_manager'):
            random_action = QAction("Random Sort", menu)
            random_action.setShortcut(QKeySequence("R"))
            random_action.setCheckable(True)
            random_action.triggered.connect(lambda: self.main_window.view_mode_manager.set_random_mode())
            # Sync checked state with menu action if it exists
            if hasattr(self.main_window, 'random_action'):
                random_action.setChecked(self.main_window.random_action.isChecked())
            menu.addAction(random_action)
        
        # Custom Order
        if hasattr(self.main_window, 'set_custom_sort'):
            custom_action = QAction("Custom Sort", menu)
            custom_action.setShortcut(QKeySequence("C"))
            custom_action.setCheckable(True)
            custom_action.triggered.connect(self.main_window.set_custom_sort)
            # Sync checked state with menu action if it exists
            if hasattr(self.main_window, 'custom_sort_action'):
                custom_action.setChecked(self.main_window.custom_sort_action.isChecked())
            menu.addAction(custom_action)
        
        # Calculate position: above the widget, aligned to left edge
        # Get widget's bottom-left corner in global coordinates
        widget_bottom_left = self.mapToGlobal(QPoint(0, self.height()))
        # Position menu above the widget (subtract status bar height)
        menu_height = menu.sizeHint().height() + self.height()  # Use status bar widget height as margin
        menu_pos = QPoint(widget_bottom_left.x(), widget_bottom_left.y() - menu_height - 4) # sub 2 to acct for border
        
        # Show menu at calculated position
        menu.exec(menu_pos)

class ClickableFitModeLabel(QLabel):
    """A clickable QLabel for the fit mode section that toggles actual size in browse mode"""
    
    def __init__(self, text="", parent=None):
        super().__init__(text, parent)
        self.main_window = None
        # Enable mouse tracking to show pointer cursor on hover when in browse mode
        self._update_cursor()
    
    def set_main_window(self, main_window):
        """Set the main window reference"""
        self.main_window = main_window
        self._update_cursor()
    
    def _update_cursor(self):
        """Update cursor based on view mode"""
        if self.main_window and getattr(self.main_window, 'current_view_mode', '') == 'browse':
            self.setCursor(Qt.PointingHandCursor)
        else:
            self.setCursor(Qt.ArrowCursor)
    
    def mousePressEvent(self, event: QMouseEvent):
        """Handle mouse clicks to toggle actual size in browse mode"""
        if event.button() in (Qt.LeftButton, Qt.RightButton):
            if self.main_window and getattr(self.main_window, 'current_view_mode', '') == 'browse':
                # Toggle actual size (same as pressing "A" key)
                if hasattr(self.main_window, 'toggle_actual_size'):
                    self.main_window.toggle_actual_size()
        super().mousePressEvent(event)

class ClickableImageGenIndicatorLabel(QLabel):
    """Clickable status indicator while a model background task runs (image or caption)."""

    _CLICK_HINT = "click for menu, double-click for job queue (⌘J)"

    def __init__(self, text="🔴", parent=None):
        super().__init__(text, parent)
        self.main_window = None
        self._live_task_info_browser: Optional[QTextBrowser] = None
        self._live_task_info_timer: Optional[QTimer] = None
        self._live_task_info_signal_connected = False
        self._single_click_timer = QTimer(self)
        self._single_click_timer.setSingleShot(True)
        self._single_click_timer.timeout.connect(self._on_single_click_timeout)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip(
            f"Image generation in progress ({self._CLICK_HINT})"
        )

    def _task_tooltip(self, summary: str) -> str:
        return f"{summary} ({self._CLICK_HINT})"

    def set_task_kind(self, task_kind: str) -> None:
        if task_kind == "caption":
            self.setText("🟡")
            self.setToolTip(self._task_tooltip("AI caption in progress"))
        elif task_kind == "cooldown":
            self.setText("🔵")
            self.setToolTip(
                self._task_tooltip(
                    "Cooling down between image generations"
                )
            )
        else:
            self.setText("🔴")
            self.setToolTip(
                self._task_tooltip("Image generation in progress")
            )

    def set_main_window(self, main_window):
        self.main_window = main_window

    def mousePressEvent(self, event: QMouseEvent):
        if not self.main_window:
            super().mousePressEvent(event)
            return
        if event.button() == Qt.RightButton:
            self._show_imagegen_menu()
            event.accept()
            return
        if event.button() == Qt.LeftButton:
            app = QApplication.instance()
            interval = app.doubleClickInterval() if app else 400
            self._single_click_timer.start(interval)
            event.accept()
            return
        super().mousePressEvent(event)

    def _on_single_click_timeout(self) -> None:
        from shiboken6 import isValid

        if not isValid(self) or not self.main_window:
            return
        self._show_imagegen_menu()

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.LeftButton and self.main_window:
            self._single_click_timer.stop()
            self._toggle_job_queue_dialog()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def _toggle_job_queue_dialog(self) -> None:
        try:
            from imagegen_plugins.image_gen_job_queue_dialog import (
                show_imagegen_job_queue_dialog,
            )

            show_imagegen_job_queue_dialog(self.main_window)
        except ImportError:
            pass

    def _refresh_live_task_info(self, *, force: bool = False) -> None:
        browser = self._live_task_info_browser
        if browser is None or not self.main_window:
            return
        try:
            from imagegen_plugins.image_gen_controller import get_imagegen_controller

            controller = get_imagegen_controller(self.main_window)
            if not force and not controller.task_status_display_needs_refresh():
                return
            info_html = controller.get_task_queue_status_info_html()
        except ImportError:
            return
        if not info_html:
            return
        _apply_task_info_html_to_browser(browser, info_html)

    def _refresh_live_task_info_on_signal(self) -> None:
        self._refresh_live_task_info(force=True)

    def _refresh_live_task_info_on_timer(self) -> None:
        self._refresh_live_task_info(force=False)

    def _start_live_task_info_updates(
        self, info_browser: QTextBrowser, menu: QMenu
    ) -> None:
        self._stop_live_task_info_updates()
        self._live_task_info_browser = info_browser
        try:
            from imagegen_plugins.image_gen_controller import get_imagegen_controller

            controller = get_imagegen_controller(self.main_window)
            controller.task_status_info_changed.connect(
                self._refresh_live_task_info_on_signal
            )
            self._live_task_info_signal_connected = True
        except ImportError:
            pass
        timer = QTimer(self)
        timer.setInterval(500)
        timer.timeout.connect(self._refresh_live_task_info_on_timer)
        timer.start()
        self._live_task_info_timer = timer
        menu.aboutToHide.connect(self._stop_live_task_info_updates)

    def _stop_live_task_info_updates(self) -> None:
        from shiboken6 import isValid

        self._live_task_info_browser = None
        timer = self._live_task_info_timer
        self._live_task_info_timer = None
        if timer is not None:
            try:
                timer.stop()
            except (RuntimeError, SystemError):
                pass
            try:
                if isValid(timer):
                    timer.deleteLater()
            except (RuntimeError, SystemError):
                pass
        if self._live_task_info_signal_connected:
            try:
                if isValid(self) and self.main_window:
                    from imagegen_plugins.image_gen_controller import (
                        get_imagegen_controller,
                    )

                    controller = get_imagegen_controller(self.main_window)
                    controller.task_status_info_changed.disconnect(
                        self._refresh_live_task_info_on_signal
                    )
            except (ImportError, TypeError, RuntimeError, SystemError):
                pass
            finally:
                self._live_task_info_signal_connected = False

    def _show_imagegen_menu(self):
        if not self.main_window:
            return
        menu = QMenu(self)
        menu.setStyleSheet(_status_bar_popup_menu_stylesheet())
        info_html = ""
        try:
            from imagegen_plugins.image_gen_controller import get_imagegen_controller

            info_html = get_imagegen_controller(
                self.main_window
            ).get_task_queue_status_info_html()
        except ImportError:
            pass
        if info_html:
            info_panel = QWidget()
            info_layout = QVBoxLayout(info_panel)
            info_layout.setContentsMargins(0, 0, 0, 0)
            info_layout.setSpacing(0)
            info_browser = QTextBrowser(info_panel)
            configure_task_info_text_browser(
                info_browser,
                self.main_window,
                max_width=440,
                fixed_width=440,
            )
            _apply_task_info_html_to_browser(info_browser, info_html)
            try:
                from imagegen_plugins.job_prompt_tooltip import (
                    install_delayed_prompt_tooltip,
                )

                install_delayed_prompt_tooltip(
                    info_browser,
                    get_imagegen_controller(self.main_window).active_job_full_prompt(),
                )
            except ImportError:
                pass
            info_layout.addWidget(info_browser)
            progressive_row = _progressive_images_row_widget(self.main_window, info_panel)
            if progressive_row is not None:
                info_layout.addWidget(progressive_row)
            info_action = QWidgetAction(menu)
            info_action.setDefaultWidget(info_panel)
            menu.addAction(info_action)
            menu.addSeparator()
            self._start_live_task_info_updates(info_browser, menu)
        cancel_action = QAction("🚫 Cancel Generation / Caption", menu)
        cancel_action.triggered.connect(self._cancel_generation)
        menu.addAction(cancel_action)
        widget_bottom_left = self.mapToGlobal(QPoint(0, self.height()))
        menu_height = menu.sizeHint().height() + self.height()
        menu_pos = QPoint(widget_bottom_left.x(), widget_bottom_left.y() - menu_height - 4)
        try:
            menu.exec(menu_pos)
        finally:
            from shiboken6 import isValid

            if isValid(self):
                self._stop_live_task_info_updates()

    def _cancel_generation(self):
        if not self.main_window:
            return
        try:
            from imagegen_plugins.image_gen_controller import get_imagegen_controller
            get_imagegen_controller(self.main_window).cancel_generation()
        except ImportError:
            pass


class ClickableFileCountLabel(QLabel):
    """A clickable QLabel for the file count section that shows a context menu to toggle background extraction"""
    
    def __init__(self, text="", parent=None):
        super().__init__(text, parent)
        self.main_window = None
        # Enable mouse tracking to show pointer cursor on hover
        self.setCursor(Qt.PointingHandCursor)
    
    def set_main_window(self, main_window):
        """Set the main window reference for creating context menu"""
        self.main_window = main_window
    
    def mousePressEvent(self, event: QMouseEvent):
        """Handle mouse clicks to show background extraction toggle menu"""
        if event.button() in (Qt.LeftButton, Qt.RightButton) and self.main_window:
            self._show_background_extraction_menu()
        super().mousePressEvent(event)
    
    def _show_background_extraction_menu(self):
        """Show context menu with background extraction toggle option"""
        if not self.main_window:
            return
        
        # Create context menu with same styling as status bar
        menu = QMenu(self)
        menu.setStyleSheet(_status_bar_popup_menu_stylesheet())
        
        # Get current setting
        from config import get_config
        config = get_config()
        settings = config.load_settings()
        background_clip_enabled = settings.get('background_clip_enabled', False)
        
        # Add toggle action - show opposite of current state
        if background_clip_enabled:
            toggle_action = QAction("Turn off Background Extracts", menu)
            toggle_action.triggered.connect(lambda: self._toggle_background_extraction(False))
        else:
            toggle_action = QAction("Turn on Background Extracts", menu)
            toggle_action.triggered.connect(lambda: self._toggle_background_extraction(True))
        menu.addAction(toggle_action)
        
        # Calculate position: above the widget, aligned to left edge
        # Get widget's bottom-left corner in global coordinates
        widget_bottom_left = self.mapToGlobal(QPoint(0, self.height()))
        # Position menu above the widget (subtract status bar height)
        menu_height = menu.sizeHint().height() + self.height()  # Use status bar widget height as margin
        menu_pos = QPoint(widget_bottom_left.x(), widget_bottom_left.y() - menu_height - 4) # sub 4 to acct for border
        
        # Show menu at calculated position
        menu.exec(menu_pos)
    
    def _toggle_background_extraction(self, enabled: bool):
        """Toggle the background extraction setting and update the process"""
        if not self.main_window:
            return
        
        # Update setting via on_settings_changed to trigger all the necessary handlers
        if hasattr(self.main_window, 'on_settings_changed'):
            self.main_window.on_settings_changed({'background_clip_enabled': enabled})

class ClickableDateLabel(QLabel):
    """A clickable QLabel for the date section that shows a context menu with date display options"""
    
    def __init__(self, text="", parent=None):
        super().__init__(text, parent)
        self.main_window = None
        # Enable mouse tracking to show pointer cursor on hover
        self.setCursor(Qt.PointingHandCursor)
    
    def set_main_window(self, main_window):
        """Set the main window reference for creating context menu"""
        self.main_window = main_window
    
    def mousePressEvent(self, event: QMouseEvent):
        """Handle mouse clicks to show date context menu"""
        if event.button() in (Qt.LeftButton, Qt.RightButton) and self.main_window:
            self._show_date_menu()
        super().mousePressEvent(event)
    
    def _show_date_menu(self):
        """Show context menu with date display options above the date section"""
        if not self.main_window:
            return
        
        # Create context menu with same styling as status bar
        menu = QMenu(self)
        menu.setStyleSheet(_status_bar_popup_menu_stylesheet())
        
        # Get current setting
        from config import get_config
        config = get_config()
        settings = config.load_settings()
        use_exif_date = settings.get('use_exif_date', True)  # Default: use EXIF if available
        
        # Add "Always use file date" action
        always_file_date_action = QAction("Always Use File Date", menu)
        always_file_date_action.setCheckable(True)
        always_file_date_action.setChecked(not use_exif_date)
        always_file_date_action.triggered.connect(lambda: self._set_date_preference(False))
        menu.addAction(always_file_date_action)
        
        # Add "Use EXIF date if available" action
        use_exif_date_action = QAction("Use EXIF Date if Available", menu)
        use_exif_date_action.setCheckable(True)
        use_exif_date_action.setChecked(use_exif_date)
        use_exif_date_action.triggered.connect(lambda: self._set_date_preference(True))
        menu.addAction(use_exif_date_action)
        
        # Calculate position: above the widget, aligned to left edge
        # Get widget's bottom-left corner in global coordinates
        widget_bottom_left = self.mapToGlobal(QPoint(0, self.height()))
        # Position menu above the widget (subtract status bar height)
        menu_height = menu.sizeHint().height() + self.height()  # Use status bar widget height as margin
        menu_pos = QPoint(widget_bottom_left.x(), widget_bottom_left.y() - menu_height - 4) # sub 4 to acct for border
        
        # Show menu at calculated position
        menu.exec(menu_pos)
    
    def _set_date_preference(self, use_exif: bool):
        """Set the date display preference and update the date section"""
        if not self.main_window:
            return
        
        from config import get_config
        config = get_config()
        config.update_setting('use_exif_date', use_exif)
        
        # Update the date section immediately
        if hasattr(self.main_window, 'status_bar_manager'):
            current_image_path = self.main_window.get_current_image_path()
            self.main_window.status_bar_manager.update_date_section(self.main_window, current_image_path)
class StatusBarSection:
    """Represents a single section in the status bar"""
    def __init__(self, section_id: str, width_percent: float, widget: QWidget = None, 
                 is_spacer: bool = False, is_progress: bool = False):
        self.section_id = section_id
        self.width_percent = width_percent
        self.widget = widget
        self.is_spacer = is_spacer
        self.is_progress = is_progress
        self.visible = True

class StatusBarConfig:
    """Configuration for status bar layout"""
    
    # Progress bar constants
    PROGRESS_BAR_WIDTH = 200
    PROGRESS_BAR_MIN_WIDTH = 150
    PROGRESS_BAR_MAX_WIDTH = 300
    
    # Section IDs
    SECTION_FILENAME = "filename"
    SECTION_DIMENSIONS = "dimensions"
    SECTION_DIRECTORY = "directory"
    SECTION_DATE = "date"
    SECTION_SORT_STATE = "sort_state"
    SECTION_FIT_MODE = "fit_mode"
    SECTION_FILE_COUNT = "file_count"
    SECTION_FILTER = "filter"
    SECTION_THUMBNAIL_STATUS = "thumbnail_status"
    SECTION_MESSAGE = "message"
    SECTION_PROGRESS = "progress"
    
    def __init__(self):
        # Default layout configuration
        self.sections: List[StatusBarSection] = [
            # Order: sort_state | filename (full path) | dimensions | date | filter | fit/actual | file count
            StatusBarSection(self.SECTION_SORT_STATE, 10.0),
            StatusBarSection(self.SECTION_FILENAME, 25.0),  # Increased for full path
            StatusBarSection(self.SECTION_DIMENSIONS, 10.0),
            StatusBarSection(self.SECTION_DATE, 16.0),  # Increased for full date/time format (yyyy/mm/dd hh:mm:ss)
            StatusBarSection(self.SECTION_FILTER, 12.0),
            StatusBarSection(self.SECTION_FIT_MODE, 10.0),
            StatusBarSection(self.SECTION_FILE_COUNT, 8.0),
            
            # Right side - status, message, and progress
            StatusBarSection(self.SECTION_THUMBNAIL_STATUS, 6.0),
            StatusBarSection(self.SECTION_MESSAGE, 10.0),
            StatusBarSection(self.SECTION_PROGRESS, 8.0, is_progress=True),
        ]
        
        # Widget storage
        self.widgets: Dict[str, QWidget] = {}
        
    def get_section(self, section_id: str) -> Optional[StatusBarSection]:
        """Get a section by ID"""
        for section in self.sections:
            if section.section_id == section_id:
                return section
        return None
    
    def get_widget(self, section_id: str) -> Optional[QWidget]:
        """Get a widget by section ID"""
        return self.widgets.get(section_id)
    
    def set_widget(self, section_id: str, widget: QWidget):
        """Set a widget for a section"""
        self.widgets[section_id] = widget
        section = self.get_section(section_id)
        if section:
            section.widget = widget
    
    def get_visible_sections(self) -> List[StatusBarSection]:
        """Get all visible sections"""
        return [section for section in self.sections if section.visible]
    
class StatusBarManager:
    """Manages the status bar layout and updates"""
    
    def __init__(self, status_bar: QStatusBar):
        self.status_bar = status_bar
        self.config = StatusBarConfig()
        self.main_window = None
        
        # Cache for file count to avoid scanning directory every 2 seconds
        self._cached_file_count = None
        self._cached_directory = None
        self._cached_filter_pattern = None

        # Image generation indicator (added/removed dynamically; not in _apply_layout)
        self._imagegen_indicator_widget: Optional[QLabel] = None
        
        # Completely disable the default message area by setting size policy
        self.status_bar.setSizeGripEnabled(False)  # Remove size grip
        # Force the status bar to not reserve space for messages
        self.status_bar.setContentsMargins(0, 0, 0, 0)
        
        # Clear any existing message and set empty message to minimize space
        self.status_bar.clearMessage()
        self.status_bar.showMessage("", 0)  # Set empty message with 0 duration
        
        # Override the status bar's message handling to prevent space reservation
        self.status_bar.messageChanged.connect(self._on_message_changed)
        
        self._setup_widgets()
        self._apply_layout()
    
    def set_main_window(self, main_window):
        """Set the main window reference and update clickable widgets"""
        self.main_window = main_window
        # Subscribe to model changes for status bar updates
        if hasattr(main_window, 'event_bus') and main_window.event_bus:
            from event_bus import CURRENT_IMAGE_CHANGED, DISPLAYED_IMAGES_CHANGED, DIRECTORY_LOADED, SETTINGS_CHANGED
            main_window.event_bus.subscribe(CURRENT_IMAGE_CHANGED, self._on_current_image_changed)
            main_window.event_bus.subscribe(DISPLAYED_IMAGES_CHANGED, self._on_displayed_images_changed)
            main_window.event_bus.subscribe(DIRECTORY_LOADED, self._on_directory_loaded)
            main_window.event_bus.subscribe(SETTINGS_CHANGED, self._on_settings_changed)
        # Update filter widget with main window reference
        filter_widget = self.config.get_widget(self.config.SECTION_FILTER)
        if filter_widget and isinstance(filter_widget, ClickableFilterLabel):
            filter_widget.set_main_window(main_window)
        # Update sort widget with main window reference
        sort_widget = self.config.get_widget(self.config.SECTION_SORT_STATE)
        if sort_widget and isinstance(sort_widget, ClickableSortLabel):
            sort_widget.set_main_window(main_window)
        # Update fit mode widget with main window reference
        fit_widget = self.config.get_widget(self.config.SECTION_FIT_MODE)
        if fit_widget and isinstance(fit_widget, ClickableFitModeLabel):
            fit_widget.set_main_window(main_window)
        # Update date widget with main window reference
        date_widget = self.config.get_widget(self.config.SECTION_DATE)
        if date_widget and isinstance(date_widget, ClickableDateLabel):
            date_widget.set_main_window(main_window)
        # Update file count widget with main window reference
        file_count_widget = self.config.get_widget(self.config.SECTION_FILE_COUNT)
        if file_count_widget and isinstance(file_count_widget, ClickableFileCountLabel):
            file_count_widget.set_main_window(main_window)
    
    def _on_settings_changed(self, new_settings: dict):
        """Handle SETTINGS_CHANGED event - update filter section when filter changes"""
        if self.main_window and ('filter_pattern' in new_settings or 'ignore_exif_rotation' in new_settings):
            self.invalidate_file_count_cache()
            if 'filter_pattern' in new_settings:
                self._update_filter_section(self.main_window)

    def _on_directory_loaded(self, directory, displayed_count=None, external_load=None):
        """Handle DIRECTORY_LOADED event - update status bar sections"""
        if self.main_window:
            if hasattr(self.main_window, 'update_status_bar_sections'):
                self.main_window.update_status_bar_sections()
            if hasattr(self.main_window, 'update_status_bar_current_image'):
                self.main_window.update_status_bar_current_image()

    def _on_current_image_changed(self, image_path):
        """Handle CURRENT_IMAGE_CHANGED event - update status bar"""
        if self.main_window and hasattr(self.main_window, 'update_status_bar_current_image'):
            displayed = getattr(self.main_window, 'displayed_images', None)
            self.main_window.update_status_bar_current_image(image_path, displayed)

    def _on_displayed_images_changed(self, images):
        """Handle DISPLAYED_IMAGES_CHANGED event - update status bar sections"""
        if self.main_window and hasattr(self.main_window, 'update_status_bar_sections'):
            self.main_window.update_status_bar_sections()

    def refresh_theme_styles(self):
        """Re-apply status bar section label styles after global theme change."""
        standard = f"""
            QLabel {{
                color: {_status_bar_fg_hex()};
                background-color: transparent;
                padding: 2px 5px;
            }}
        """
        message_style = f"""
            QLabel {{
                color: {_status_bar_fg_hex()};
                background-color: transparent;
                padding: 2px 5px;
                font-style: italic;
            }}
        """
        for sid in (
            self.config.SECTION_FILENAME,
            self.config.SECTION_DIMENSIONS,
            self.config.SECTION_DIRECTORY,
            self.config.SECTION_DATE,
            self.config.SECTION_SORT_STATE,
            self.config.SECTION_FIT_MODE,
            self.config.SECTION_FILTER,
            self.config.SECTION_FILE_COUNT,
            self.config.SECTION_THUMBNAIL_STATUS,
        ):
            w = self.config.get_widget(sid)
            if w:
                w.setStyleSheet(standard)
        mw = self.config.get_widget(self.config.SECTION_MESSAGE)
        if mw:
            mw.setStyleSheet(message_style)
        if self._imagegen_indicator_widget is not None:
            self._imagegen_indicator_widget.setStyleSheet(standard)
        if self.main_window:
            self.update_fit_mode_section(self.main_window)
            self._update_filter_section(self.main_window)

    def _on_message_changed(self, message):
        """Override message changes to prevent space reservation"""
        if message and message.strip():
            # If there's a real message, clear it immediately to prevent space reservation
            self.status_bar.clearMessage()
    
    def _setup_widgets(self):
        """Create and configure all status bar widgets"""
        
        # Filename section
        filename_widget = QLabel("No file")
        filename_widget.setStyleSheet(f"""
            QLabel {{
                color: {_status_bar_fg_hex()};
                background-color: transparent;
                padding: 2px 5px;
            }}
        """)
        # Allow the filename widget to expand and show full text
        filename_widget.setWordWrap(False)
        filename_widget.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.config.set_widget(self.config.SECTION_FILENAME, filename_widget)
        
        # Dimensions section
        dimensions_widget = QLabel("0 x 0")
        dimensions_widget.setStyleSheet(f"""
            QLabel {{
                color: {_status_bar_fg_hex()};
                background-color: transparent;
                padding: 2px 5px;
            }}
        """)
        self.config.set_widget(self.config.SECTION_DIMENSIONS, dimensions_widget)
        
        # Directory section
        directory_widget = QLabel("No directory")
        directory_widget.setStyleSheet(f"""
            QLabel {{
                color: {_status_bar_fg_hex()};
                background-color: transparent;
                padding: 2px 5px;
            }}
        """)
        self.config.set_widget(self.config.SECTION_DIRECTORY, directory_widget)
        
        # Date section - clickable with context menu
        date_widget = ClickableDateLabel("--")
        date_widget.setStyleSheet(f"""
            QLabel {{
                color: {_status_bar_fg_hex()};
                background-color: transparent;
                padding: 2px 5px;
            }}
        """)
        # Enable HTML text format for icon embedding
        date_widget.setTextFormat(Qt.RichText)
        self.config.set_widget(self.config.SECTION_DATE, date_widget)
        
        # Sort state section - clickable with context menu
        sort_widget = ClickableSortLabel("Date ↑")
        sort_widget.setStyleSheet(f"""
            QLabel {{
                color: {_status_bar_fg_hex()};
                background-color: transparent;
                padding: 2px 5px;
            }}
        """)
        self.config.set_widget(self.config.SECTION_SORT_STATE, sort_widget)
        
        # Fit mode section - clickable in browse mode
        fit_widget = ClickableFitModeLabel("Fit to Window")
        fit_widget.setStyleSheet(f"""
            QLabel {{
                color: {_status_bar_fg_hex()};
                background-color: transparent;
                padding: 2px 5px;
            }}
        """)
        self.config.set_widget(self.config.SECTION_FIT_MODE, fit_widget)
        
        # Filter section
        filter_widget = ClickableFilterLabel("Filter: *")
        filter_widget.setStyleSheet(f"""
            QLabel {{
                color: {_status_bar_fg_hex()};
                background-color: transparent;
                padding: 2px 5px;
            }}
        """)
        # Main window reference will be set via set_main_window() after StatusBarManager initialization
        self.config.set_widget(self.config.SECTION_FILTER, filter_widget)
        
        # File count section (reuse existing or create new)
        if hasattr(self.status_bar.parent(), 'file_count_label'):
            # If reusing existing widget, check if it's already clickable
            existing_widget = self.status_bar.parent().file_count_label
            if not isinstance(existing_widget, ClickableFileCountLabel):
                # Replace with clickable version
                file_count_widget = ClickableFileCountLabel(existing_widget.text())
                file_count_widget.setStyleSheet(existing_widget.styleSheet())
                self.config.set_widget(self.config.SECTION_FILE_COUNT, file_count_widget)
            else:
                self.config.set_widget(self.config.SECTION_FILE_COUNT, existing_widget)
        else:
            # Create a new clickable file count widget
            file_count_widget = ClickableFileCountLabel("0 files")
            file_count_widget.setStyleSheet(f"""
                QLabel {{
                    color: {_status_bar_fg_hex()};
                    background-color: transparent;
                    padding: 2px 5px;
                }}
            """)
            self.config.set_widget(self.config.SECTION_FILE_COUNT, file_count_widget)
        
        # Thumbnail status section (reuse existing or create new)
        if hasattr(self.status_bar.parent(), 'thumbnail_status_label'):
            self.config.set_widget(self.config.SECTION_THUMBNAIL_STATUS, 
                                 self.status_bar.parent().thumbnail_status_label)
        else:
            # Create a new thumbnail status widget if not available
            thumbnail_status_widget = QLabel("")
            thumbnail_status_widget.setStyleSheet(f"""
                QLabel {{
                    color: {_status_bar_fg_hex()};
                    background-color: transparent;
                    padding: 2px 5px;
                }}
            """)
            self.config.set_widget(self.config.SECTION_THUMBNAIL_STATUS, thumbnail_status_widget)
        
        # Message section
        message_widget = QLabel("")
        message_widget.setParent(self.status_bar)  # Ensure proper parenting
        message_widget.setFocusPolicy(Qt.NoFocus)  # Don't steal keyboard when message appears
        message_widget.setStyleSheet(f"""
            QLabel {{
                color: {_status_bar_fg_hex()};
                background-color: transparent;
                padding: 2px 5px;
                font-style: italic;
            }}
        """)
        message_widget.hide()  # Start hidden
        self.config.set_widget(self.config.SECTION_MESSAGE, message_widget)
        
        # Progress bars are now handled separately - not part of status bar
        # Just create placeholder widgets for compatibility
        from PySide6.QtWidgets import QProgressBar
        progress_widget = QProgressBar()
        progress_widget.setVisible(False)
        self.config.set_widget(self.config.SECTION_PROGRESS, progress_widget)
    
    def _create_separator(self):
        """Create a dull greenish yellow separator widget"""
        separator = QWidget()
        separator.setFixedWidth(3)
        separator.setFixedHeight(20)  # Match status bar height
        separator.setStyleSheet("""
            QWidget {
                background-color: #555555;
                width: 1px;
                border-right: 1px solid #ffffff;
                border: none;
            }
        """)
        return separator
    
    def _ensure_widgets_exist(self):
        """Ensure all required widgets exist before applying layout"""
        # Check if widgets exist, if not recreate them
        for section in self.config.sections:
            if not section.widget:
                # Recreate the widget for this section
                if section.section_id == self.config.SECTION_FILENAME:
                    widget = QLabel("")
                    widget.setStyleSheet(f"color: {_status_bar_fg_hex()}; font-weight: bold;")
                    widget.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
                elif section.section_id == self.config.SECTION_DIMENSIONS:
                    widget = QLabel("")
                    widget.setStyleSheet(f"color: {_status_bar_fg_hex()};")
                    widget.setAlignment(Qt.AlignCenter)
                elif section.section_id == self.config.SECTION_DIRECTORY:
                    widget = QLabel("")
                    widget.setStyleSheet(f"color: {_status_bar_fg_hex()};")
                    widget.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
                elif section.section_id == self.config.SECTION_DATE:
                    widget = ClickableDateLabel("")
                    widget.setStyleSheet(f"color: {_status_bar_fg_hex()};")
                    widget.setAlignment(Qt.AlignCenter)
                    # Enable HTML text format for icon embedding
                    widget.setTextFormat(Qt.RichText)
                    # Set main window reference if available
                    if self.main_window:
                        widget.set_main_window(self.main_window)
                elif section.section_id == self.config.SECTION_SORT_STATE:
                    widget = ClickableSortLabel("")
                    widget.setStyleSheet(f"color: {_status_bar_fg_hex()};")
                    widget.setAlignment(Qt.AlignCenter)
                    # Set main window reference if available
                    if self.main_window:
                        widget.set_main_window(self.main_window)
                elif section.section_id == self.config.SECTION_FIT_MODE:
                    widget = ClickableFitModeLabel("")
                    widget.setStyleSheet(f"color: {_status_bar_fg_hex()};")
                    widget.setAlignment(Qt.AlignCenter)
                    # Set main window reference if available
                    if self.main_window:
                        widget.set_main_window(self.main_window)
                elif section.section_id == self.config.SECTION_FILE_COUNT:
                    widget = QLabel("")
                    widget.setStyleSheet(f"color: {_status_bar_fg_hex()};")
                    widget.setAlignment(Qt.AlignCenter)
                elif section.section_id == self.config.SECTION_FILTER:
                    widget = ClickableFilterLabel("")
                    widget.setStyleSheet(f"color: {_status_bar_fg_hex()};")
                    widget.setAlignment(Qt.AlignCenter)
                    # Set main window reference if available
                    if self.main_window:
                        widget.set_main_window(self.main_window)
                elif section.section_id == self.config.SECTION_THUMBNAIL_STATUS:
                    widget = QLabel("")
                    widget.setStyleSheet(f"color: {_status_bar_fg_hex()};")
                    widget.setAlignment(Qt.AlignCenter)
                elif section.section_id == self.config.SECTION_MESSAGE:
                    widget = QLabel("")
                    widget.setFocusPolicy(Qt.NoFocus)
                    widget.setStyleSheet(f"color: {_status_bar_fg_hex()};")
                    widget.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
                elif section.section_id == self.config.SECTION_PROGRESS:
                    widget = QProgressBar()
                    widget.setVisible(False)
                else:
                    widget = QLabel("")
                    widget.setStyleSheet(f"color: {_status_bar_fg_hex()};")
                    widget.setAlignment(Qt.AlignCenter)
                
                # Set the widget in the config
                self.config.set_widget(section.section_id, widget)
                section.widget = widget
    
    def _apply_layout(self):
        """Apply the layout to the status bar with filename priority"""
        
        # Clear the default message area
        self.status_bar.clearMessage()
        
        # Remove ALL existing widgets from status bar
        removed_count = 0
        for widget in self.status_bar.findChildren(QWidget):
            if widget.parent() == self.status_bar:
                self.status_bar.removeWidget(widget)
                removed_count += 1
        
        # Ensure all widgets are properly created before applying layout
        self._ensure_widgets_exist()
        
        # Get visible sections excluding progress bars
        visible_sections = [s for s in self.config.get_visible_sections() if not s.is_progress]
        
        # Filter out message section if it's empty
        message_widget = self.config.get_widget(self.config.SECTION_MESSAGE)
        if message_widget and (not message_widget.text() or not message_widget.isVisible()):
            visible_sections = [s for s in visible_sections if s.section_id != self.config.SECTION_MESSAGE]
        
        # Order sections: sort_state, filter, filename, dimensions, date, fit_mode, file_count, thumbnail_status
        final_sections = []
        section_order = [
            self.config.SECTION_SORT_STATE,
            self.config.SECTION_FILTER,
            self.config.SECTION_FILENAME,
            self.config.SECTION_DIMENSIONS,
            self.config.SECTION_DATE,
            self.config.SECTION_FIT_MODE,
            self.config.SECTION_FILE_COUNT,
            self.config.SECTION_THUMBNAIL_STATUS
        ]
        
        for section_id in section_order:
            for section in visible_sections:
                if section.section_id == section_id:
                    final_sections.append(section)
                    break
        
        # Add main content widgets in order with separators
        for i, section in enumerate(final_sections):
            if section.is_spacer:
                # Create a spacer widget
                spacer = QWidget()
                spacer.setFixedWidth(10)  # Fixed small width for spacers
                self.status_bar.addPermanentWidget(spacer, 0)  # No stretch
            elif section.widget:
                if section.section_id == self.config.SECTION_FILENAME:
                    # Filename gets maximum stretch to take available space
                    self.status_bar.addPermanentWidget(section.widget, 1000)
                else:
                    # Other sections get minimal stretch
                    stretch = 1
                    self.status_bar.addPermanentWidget(section.widget, stretch)
            
            # Add separator after each section except the last one and not after file count
            if (i < len(final_sections) - 1 and 
                section.section_id != self.config.SECTION_FILE_COUNT):
                separator = self._create_separator()
                self.status_bar.addPermanentWidget(separator, 0)  # No stretch
        
        # Progress bars are now handled separately - not added to status bar
        
    def show_message(self, message: str, duration: int = 0):
        """Show a message in the message section"""
        # Clear the default status bar message area first
        self.status_bar.clearMessage()
        
        message_widget = self.config.get_widget(self.config.SECTION_MESSAGE)
        if message_widget:
            current_text = message_widget.text()
            current_visible = message_widget.isVisible()
            
            # Only update if message or visibility actually changes
            if current_text != message or not current_visible:
                message_widget.setText(message)
                message_widget.setVisible(True)
                # NO LAYOUT REAPPLICATION - just show the message directly
            
            # Auto-clear after duration if specified
            if duration > 0:
                from PySide6.QtCore import QTimer
                timer = QTimer()
                timer.setSingleShot(True)
                timer.timeout.connect(self.clear_message)
                timer.start(duration)
    
    def clear_message(self):
        """Clear the message section"""
        # Clear the default status bar message area first
        self.status_bar.clearMessage()
        
        message_widget = self.config.get_widget(self.config.SECTION_MESSAGE)
        if message_widget:
            current_text = message_widget.text()
            current_visible = message_widget.isVisible()
            
            # Only update if message is not already empty or widget is visible
            if current_text != "" or current_visible:
                message_widget.setText("")
                message_widget.setVisible(False)
                # NO LAYOUT REAPPLICATION - just hide the message directly

    def show_model_task_indicator(self, task_kind: str) -> None:
        """Show status-bar dot while the model worker is processing (red=image, yellow=caption)."""
        indicator = self._imagegen_indicator_widget
        if indicator is not None:
            indicator.set_task_kind(task_kind)
            return
        indicator = ClickableImageGenIndicatorLabel()
        indicator.set_task_kind(task_kind)
        if self.main_window:
            indicator.set_main_window(self.main_window)
        indicator.setStyleSheet(f"""
            QLabel {{
                color: {_status_bar_fg_hex()};
                background-color: transparent;
                padding: 2px 6px;
            }}
        """)
        indicator.setAlignment(Qt.AlignCenter)
        self._imagegen_indicator_widget = indicator
        self.status_bar.addPermanentWidget(indicator, 0)

    def hide_model_task_indicator(self) -> None:
        """Remove the model-task indicator from the status bar."""
        indicator = self._imagegen_indicator_widget
        if indicator is None:
            return
        self._imagegen_indicator_widget = None
        if isinstance(indicator, ClickableImageGenIndicatorLabel):
            indicator._single_click_timer.stop()
            indicator._stop_live_task_info_updates()
        self.status_bar.removeWidget(indicator)
        indicator.hide()
        indicator.deleteLater()

    def show_imagegen_running_indicator(self) -> None:
        """Deprecated: use show_model_task_indicator('generate')."""
        self.show_model_task_indicator("generate")

    def hide_imagegen_running_indicator(self) -> None:
        """Deprecated: use hide_model_task_indicator()."""
        self.hide_model_task_indicator()

    def update_status_bar_sections(self, main_window):
        """Update all status bar sections with current data from main window.
        
        This updates ALL sections including image-specific ones (filename, directory, date, dimensions).
        For image-specific updates only, use _update_status_bar_current_image() instead.
        
        PERFORMANCE: Caches get_displayed_images() and get_current_image_path() to avoid redundant calls
        when updating multiple sections.
        """
        # PERFORMANCE: Cache these values once to avoid redundant calls across multiple section updates
        # File path remains the source of truth - we're just caching the lookup results
        displayed = main_window.get_displayed_images()
        current_image_path = main_window.get_current_image_path()
        
        # Update image-specific sections first (filename, date, dimensions)
        # These must always reflect the currently active image
        # Pass cached values to avoid redundant calls
        self.update_filename_section(main_window, current_image_path, displayed)
        
        # Update dimensions
        self.update_dimensions_section(main_window, current_image_path, displayed)
        self.update_date_section(main_window, current_image_path)
        # Note: directory section removed - full path now shown in filename section
        
        # Update other sections (sort state, filter, fit mode, file count)
        self._update_sort_state_section(main_window)
        
        # Update filter
        self._update_filter_section(main_window)
        
        # Update fit mode
        self.update_fit_mode_section(main_window)
        
        # Invalidate file count cache when status bar is fully updated (directory may have changed)
        self.invalidate_file_count_cache()
        
        # Update file count
        self._update_file_count_section(main_window)
        


    def update_filename_section(self, main_window, current_image_path=None, displayed=None):
        """Update filename section
        
        Args:
            main_window: Main window instance
            current_image_path: Optional cached current image path to avoid redundant call.
                               If None, will call get_current_image_path(). File path remains source of truth.
            displayed: Optional cached list of displayed images to avoid redundant call.
                      If None, will call get_displayed_images().
        """
        filename_widget = self.config.get_widget(self.config.SECTION_FILENAME)
        if not filename_widget:
            return
        
        # PERFORMANCE: Use cached displayed list if provided, otherwise fetch it
        if displayed is None:
            displayed = main_window.get_displayed_images()
        if not displayed:
            filename_widget.setText(f"No files available for display. Check filter pattern, currently set to: {main_window.filter_pattern}")
            return
            
        # PERFORMANCE: Use cached current_image_path if provided, otherwise fetch it
        # File path remains the source of truth - we're just caching the lookup result
        if current_image_path is None:
            current_image_path = main_window.get_current_image_path()
        
        if current_image_path:
            try:
                # Show full path instead of just basename
                full_path = current_image_path
                # Replace home directory with ~ for better readability
                home_dir = os.path.expanduser("~")
                if full_path.startswith(home_dir):
                    full_path = "~" + full_path[len(home_dir):]
                filename_widget.setText(full_path)
            except (IndexError, TypeError):
                filename_widget.setText(f"No files available for display. Check filter pattern, currently set to: {main_window.filter_pattern}")
        else:
            filename_widget.setText(f"No files available for display. Check filter pattern, currently set to: {main_window.filter_pattern}")

    def update_dimensions_section(self, main_window, current_image_path=None, displayed=None):
        """Update dimensions section
        
        Args:
            main_window: Main window instance
            current_image_path: Optional cached current image path to avoid redundant call.
                               If None, will call get_current_image_path(). File path remains source of truth.
            displayed: Optional cached list of displayed images to avoid redundant call.
                      If None, will call get_displayed_images().
        """
        dimensions_widget = self.config.get_widget(self.config.SECTION_DIMENSIONS)
        if not dimensions_widget:
            return
        
        # PERFORMANCE: Use cached displayed list if provided, otherwise fetch it
        if displayed is None:
            displayed = main_window.get_displayed_images()
        if not displayed:
            dimensions_widget.setText("0 x 0")
            return
            
        # PERFORMANCE: Use cached current_image_path if provided, otherwise fetch it
        # File path remains the source of truth - we're just caching the lookup result
        if current_image_path is None:
            current_image_path = main_window.get_current_image_path()
        
        if current_image_path:
            try:
                width, height = main_window.get_image_info(current_image_path)[1:3]
                dimensions_widget.setText(f"{width} x {height}")
            except:
                dimensions_widget.setText("0 x 0")
        else:
            dimensions_widget.setText("0 x 0")


    def update_date_section(self, main_window, current_image_path=None):
        """Update date section with EXIF date/time if available, otherwise modification time.

        This must always reflect the file shown in the filename section.
        Shows camera emoji (📷) when using EXIF date, Ⓓ when using file date.
        Respects the use_exif_date setting from config.

        Args:
            main_window: Main window instance
            current_image_path: Optional cached current image path to avoid redundant call.
                               If None, will call get_current_image_path(). File path remains source of truth.
        """
        date_widget = self.config.get_widget(self.config.SECTION_DATE)
        if not date_widget:
            return

        # PERFORMANCE: Use cached current_image_path if provided, otherwise fetch it
        # File path remains the source of truth - we're just caching the lookup result
        # This ensures we get the same file path used by filename and directory sections
        if current_image_path is None:
            current_image_path = main_window.get_current_image_path()

        if current_image_path and os.path.exists(current_image_path):
            try:
                from datetime import datetime
                from config import get_config

                # Get user preference for date display
                config = get_config()
                settings = config.load_settings()
                prefer_exif_date = settings.get('use_exif_date', True)  # Default: use EXIF if available

                # Try to get metadata from cache (which includes EXIF date/time if available)
                use_exif_date = False
                timestamp = None

                if hasattr(main_window, 'cache_manager'):
                    # Ensure metadata exists in cache (will load it if not cached)
                    main_window.cache_manager._ensure_metadata_exists(current_image_path)
                    # Now get metadata from cache (should exist after ensure call)
                    metadata = main_window.cache_manager.get_metadata_sync(current_image_path)
                    if prefer_exif_date and metadata and hasattr(metadata, 'exif_taken_time') and metadata.exif_taken_time:
                        # Use EXIF date/time if available and user prefers it
                        timestamp = metadata.exif_taken_time
                        use_exif_date = True
                    elif metadata and hasattr(metadata, 'modified_time'):
                        # Fallback to cached mtime
                        timestamp = metadata.modified_time
                    else:
                        # Fallback to direct file stat
                        timestamp = os.path.getmtime(current_image_path)
                else:
                    # Fallback to direct file stat if cache manager not available
                    timestamp = os.path.getmtime(current_image_path)

                if timestamp:
                    date_str = datetime.fromtimestamp(timestamp).strftime("%Y/%m/%d %H:%M:%S")
                    # Add icon: camera emoji if using EXIF date, Ⓓ if using file date
                    if use_exif_date:
                        date_str += " &nbsp;&nbsp;📷"
                    else:
                        date_str += " &nbsp;&nbsp;Ⓓ"
                    date_widget.setText(date_str)
                else:
                    date_widget.setText("--")
            except (OSError, ValueError, AttributeError) as e:
                # If we can't get the date, show error indicator
                date_widget.setText("--")
        else:
            date_widget.setText("--")

    def _update_sort_state_section(self, main_window):
        """Update sort state section using consolidated sort mode properties"""
        sort_widget = self.config.get_widget(self.config.SECTION_SORT_STATE)
        if not sort_widget:
            return
        
        if hasattr(main_window, 'current_sort_mode'):
            try:
                from image_browser_window import SortMode
                sort_mode = main_window.current_sort_mode
                is_reversed = getattr(main_window, 'is_reversed', False)
                
                if sort_mode == SortMode.CUSTOM:
                    sort_widget.setText("Custom ↓" if is_reversed else "Custom ↑")
                elif sort_mode == SortMode.NAME:
                    sort_widget.setText("Name ↓" if is_reversed else "Name ↑")
                elif sort_mode == SortMode.SIZE:
                    sort_widget.setText("Size ↓" if is_reversed else "Size ↑")  # Size logic is inverted
                elif sort_mode == SortMode.FILESIZE:
                    sort_widget.setText("File Size ↓" if is_reversed else "File Size ↑")
                elif sort_mode == SortMode.RANDOM:
                    sort_widget.setText("Random ↑")
                elif sort_mode == SortMode.DUPLICATES:
                    sort_widget.setText("Duplicates")
                elif sort_mode == SortMode.EXIF_DATE:
                    sort_widget.setText("Month ↓" if is_reversed else "EXIF month ↑")
                elif sort_mode == SortMode.EXIF_YEAR:
                    sort_widget.setText("Year ↓" if is_reversed else "EXIF year ↑")
                else:  # DATE
                    sort_widget.setText("Date ↓" if is_reversed else "Date ↑")
            except Exception:
                # Ultimate fallback
                if hasattr(main_window, 'is_reversed') and main_window.is_reversed:
                    sort_widget.setText("Date ↓")
                else:
                    sort_widget.setText("Date ↑")
        else:
            # Ultimate fallback
            if hasattr(main_window, 'is_reversed') and main_window.is_reversed:
                sort_widget.setText("Date ↓ (oldest first)")
            else:
                sort_widget.setText("Date ↑ (newest first)")

    def update_fit_mode_section(self, main_window):
        """Update fit mode section"""
        widget = self.config.get_widget(self.config.SECTION_FIT_MODE)
        if not widget:
            return
            
        is_actual_size = getattr(main_window, 'is_actual_size', False)
        is_browse_view = getattr(main_window, 'current_view_mode', '') == 'browse'
        
        if not is_browse_view:
            # Show grayed out text when not in browse view
            mode_text = "Actual Size" if is_actual_size else "Fit to Window"
            widget.setText(mode_text)
            widget.setVisible(True)
            # Apply grayed out styling
            widget.setStyleSheet(f"""
                QLabel {{
                    color: {_status_bar_disabled_hex()};
                    background-color: transparent;
                    padding: 2px 5px;
                }}
            """)
        else:
            # Show normal text when in browse view
            mode_text = "Actual Size" if is_actual_size else "Fit to Window"
            widget.setText(mode_text)
            widget.setVisible(True)
            # Apply normal styling
            widget.setStyleSheet(f"""
                QLabel {{
                    color: {_status_bar_fg_hex()};
                    background-color: transparent;
                    padding: 2px 5px;
                }}
            """)
        
        # Update cursor for clickable fit mode widget
        if isinstance(widget, ClickableFitModeLabel):
            widget._update_cursor()
        
        # Update section visibility without triggering layout reapplication
        section = self.config.get_section(self.config.SECTION_FIT_MODE)
        if section:
            section.visible = True

    def _update_filter_section(self, main_window):
        """Update filter section showing current filter pattern"""
        filter_widget = self.config.get_widget(self.config.SECTION_FILTER)
        if not filter_widget:
            return
        
        is_thumbnail_view = getattr(main_window, 'current_view_mode', '') == 'thumbnail'
        is_specific_files_mode = getattr(main_window, 'specific_files_active', False)
        
        if hasattr(main_window, 'filter_pattern') and main_window.filter_pattern:
            filter_pattern = main_window.filter_pattern
            # Ensure pattern ends with * if it's a wildcard pattern
            if filter_pattern != '*' and not filter_pattern.endswith('*'):
                filter_pattern = filter_pattern + '*'
            filter_text = f"Filter: {filter_pattern}"
        else:
            filter_text = "Filter: *"
        
        filter_widget.setText(filter_text)
        filter_widget.setVisible(True)
        
        # Update cursor for clickable filter widget
        if isinstance(filter_widget, ClickableFilterLabel):
            filter_widget._update_cursor()
        
        # Apply styling based on view mode and specific files mode
        is_list_view = getattr(main_window, 'current_view_mode', '') == 'list'
        if (not is_thumbnail_view and not is_list_view) or is_specific_files_mode:
            # Show grayed out text when not in thumbnail/list view or in specific files mode
            filter_widget.setStyleSheet(f"""
                QLabel {{
                    color: {_status_bar_disabled_hex()};
                    background-color: transparent;
                    padding: 2px 5px;
                }}
            """)
        else:
            # Show normal text when in thumbnail or list view and not in specific files mode
            filter_widget.setStyleSheet(f"""
                QLabel {{
                    color: {_status_bar_fg_hex()};
                    background-color: transparent;
                    padding: 2px 5px;
                }}
            """)

    def invalidate_file_count_cache(self):
        """Invalidate the cached file count (call when directory or filter changes)"""
        self._cached_file_count = None
        self._cached_directory = None
        self._cached_filter_pattern = None
    
    def _are_all_files_in_same_directory(self, main_window):
        """Check if all displayed images are in the same directory.
        Pure string compare up to last slash - no os.path calls."""
        displayed_images = main_window.get_displayed_images() if hasattr(main_window, 'get_displayed_images') else getattr(main_window, 'displayed_images', None)
        if not displayed_images:
            return True
        
        cache_key = id(displayed_images)
        if cache_key == getattr(self, '_same_dir_cache_key', None):
            return self._same_dir_cache_result
        self._same_dir_cache_key = cache_key
        
        seen_prefix = None
        for path in displayed_images:
            if path:
                idx = path.rfind('/')
                prefix = path[:idx] if idx >= 0 else ''
                if seen_prefix is None:
                    seen_prefix = prefix
                elif prefix != seen_prefix:
                    self._same_dir_cache_result = False
                    return False
        self._same_dir_cache_result = True
        return True
    
    def _update_file_count_section(self, main_window):
        """Update file count section"""
        file_count_widget = self.config.get_widget(self.config.SECTION_FILE_COUNT)
        if not file_count_widget:
            return
        
        # Get background CLIP extraction status indicator
        background_indicator = ""
        is_active = False
        is_enabled = False
        if hasattr(main_window, 'background_clip_controller') and main_window.background_clip_controller:
            is_enabled = main_window.background_clip_controller.enabled
            is_active = main_window.background_clip_controller.is_background_active()
            if is_active:
                background_indicator = "● "  # Green dot when active
            elif is_enabled:
                background_indicator = "○ "  # White dot when idle but enabled
        
        # Check if multiple directories indicator should be shown
        multiple_dirs_indicator = ""
        # Get displayed images count - use method if available, otherwise use attribute
        displayed_count = 0
        if hasattr(main_window, 'get_displayed_images'):
            displayed_images = main_window.get_displayed_images()
            displayed_count = len(displayed_images) if displayed_images else 0
        elif hasattr(main_window, 'displayed_images'):
            displayed_count = len(main_window.displayed_images) if main_window.displayed_images else 0
        
        if displayed_count > 0:
            if not self._are_all_files_in_same_directory(main_window):
                multiple_dirs_indicator = " (>1 dir)"
        
        # Check if we're in "specific files" mode, in which case skip the file count logic
        if getattr(main_window, "specific_files_active", False):
            # If specific_files_mode is enabled, show just the count of displayed images
            displayed_files = len(main_window.displayed_images)
            label = f"{background_indicator}{str(displayed_files)} files{multiple_dirs_indicator}"
            file_count_widget.setText(label)
            return
        # Get total files in directory (cached to avoid expensive scan on every scroll)
        if hasattr(main_window, 'current_directory') and main_window.current_directory:
            current_dir = main_window.current_directory
            filter_pattern = getattr(main_window, 'filter_pattern', None)
            if (self._cached_directory == current_dir and
                    self._cached_filter_pattern == filter_pattern and
                    self._cached_file_count is not None):
                total_files = self._cached_file_count
            else:
                total_files = main_window.count_total_files_in_directory(current_dir)
                self._cached_file_count = total_files
                self._cached_directory = current_dir
                self._cached_filter_pattern = filter_pattern
            displayed_files = len(main_window.displayed_images) 
            
            if total_files > 0:
                label = f"{background_indicator}{displayed_files} of {total_files} files{multiple_dirs_indicator}"
                file_count_widget.setText(label)
            else:
                label = f"{background_indicator}No files"
                file_count_widget.setText(label)
        else:
            # Fallback to simple count if no directory
            displayed = main_window.get_displayed_images()
            if displayed:
                total_files = len(displayed)
                if hasattr(main_window, 'limit') and main_window.limit < 99999 and total_files >= main_window.limit:
                    label = f"{background_indicator}{total_files}+{multiple_dirs_indicator}"
                    file_count_widget.setText(label)
                else:
                    label = f"{background_indicator}{total_files}{multiple_dirs_indicator}"
                    file_count_widget.setText(label)
            else:
                label = f"{background_indicator}No files"
                file_count_widget.setText(label)

