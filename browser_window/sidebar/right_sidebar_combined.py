#!/usr/bin/env python3
"""
Right Sidebar Combined Widget - Combines Organize, Information, and Jobs in a single resizable right_sidebar
"""

from PySide6.QtCore import Qt, Signal, QEventLoop
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QSplitter, QSizePolicy, QApplication,
)

from browser_window.sidebar.sidebar_pane_chrome import (
    apply_section_pane_shell,
    apply_sidebar_pane_background,
)

from thumbnails.combined_sidebar_widget import HeaderWidget
from thumbnails.information_sidebar import InformationSidebar
from browser_window.sidebar.shortcuts_sidebar import ShortcutsSidebar
from thumbnails.sidebar_pane_layout import (
    MIN_INFORMATION_CONTENT_HEIGHT,
    MIN_JOBS_QUEUE_CONTENT_HEIGHT,
    MIN_PANE_CONTENT,
    collapse_flags_for_target,
    ensure_pane_headers_visible,
    pane_height_at_target,
    pane_min_height,
    redistribute_for_target_pane,
)
from theme.theme_service import get_active_theme

try:
    from bundle_capabilities import model_jobs_ui_enabled as _model_jobs_ui_enabled
except ImportError:
    def _model_jobs_ui_enabled() -> bool:
        return True


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
        self._jobs_feature_enabled = _model_jobs_ui_enabled()
        self.information_visible = settings.get('information_sidebar_visible', False)
        self.shortcuts_visible = settings.get('shortcuts_sidebar_visible', False)
        self.jobs_visible = (
            settings.get('jobs_visible', False) if self._jobs_feature_enabled else False
        )
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
        self._adjusting_splitter = False
        self._jobs_pane_compact = (
            bool(settings.get('jobs_pane_compact', False))
            if self._jobs_feature_enabled
            else False
        )
        self._pane_fit_targets: dict[int, int] = {}

        self.setFocusPolicy(Qt.NoFocus)
        self.setup_ui()

    def setup_ui(self):
        """Setup the right_sidebar combined widget UI"""
        self.setMinimumWidth(250)
        self.setMaximumWidth(800)
        _th = get_active_theme()
        pane_bg = _th.sidebar_background_color_hex
        apply_sidebar_pane_background(self, pane_bg)
        self.setStyleSheet(_th.right_sidebar_combined_stylesheet())

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.splitter = QSplitter(Qt.Vertical)
        self.splitter.setFocusPolicy(Qt.NoFocus)
        apply_sidebar_pane_background(self.splitter, pane_bg)
        self.splitter.setHandleWidth(_th.view_border_width_px)
        self.splitter.setStyleSheet(_th.right_sidebar_inner_splitter_stylesheet())

        self.shortcuts_section = self._create_section("Organize", "shortcuts")
        self.splitter.addWidget(self.shortcuts_section)

        self.information_widget = InformationSidebar(self.main_window, self)
        self.information_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.information_widget.information_header.hide_button.clicked.disconnect()
        self.information_widget.information_header.hide_button.clicked.connect(self._toggle_information)
        self.information_widget.information_header.title_double_clicked.connect(
            self._expand_information_pane_to_fit
        )
        self.splitter.addWidget(self.information_widget)
        self.information_widget.setVisible(self.information_visible)
        self.information_widget.information_header.hide_button.setText(
            "−" if self.information_visible else "+"
        )

        self.jobs_section = self._create_section("Job Control", "jobs")
        self.splitter.addWidget(self.jobs_section)
        if not self._jobs_feature_enabled:
            self.jobs_section.setVisible(False)
            self.jobs_visible = False

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
        self._wire_pane_titlebar_drag(
            self.information_widget.information_header,
            1,
        )
        self._wire_pane_titlebar_drag(
            self.jobs_header,
            2,
            on_drag_before=self._jobs_pane_drag_before,
            on_drag_after=self._jobs_pane_drag_after,
        )
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
            header.title_double_clicked.connect(self._expand_shortcuts_pane_to_fit)
        else:
            self.jobs_header = header
            header.hide_button.clicked.connect(self._toggle_jobs)
            header.title_double_clicked.connect(self._expand_jobs_pane_to_fit)

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
            content_area.setMinimumHeight(0)

        sect_layout.addWidget(content_area)
        _th = get_active_theme()
        pane_bg = _th.sidebar_background_color_hex
        pane_ss = _th.file_tree_pane_shell_stylesheet()
        for w in (section, content_area):
            apply_section_pane_shell(w, pane_bg, pane_ss)
        return section

    def _wire_pane_titlebar_drag(self, header, pane_idx: int, *, on_drag_before=None, on_drag_after=None) -> None:
        header.configure_pane_drag_resize(
            self.splitter,
            pane_idx,
            self._pane_min_height,
            self._pane_visibility,
            on_drag_before=on_drag_before,
            on_drag_after=on_drag_after,
        )

    def _jobs_strip_compact_available(self) -> bool:
        if not self.jobs_visible or self.jobs_widget is None:
            return False
        return self._jobs_compact_pane_height() > self._header_height_for_pane(2)

    def _jobs_pane_drag_before(self, total_dy: int, start_sizes: list[int]) -> bool:
        """Exit compact when dragging up; enter compact when cursor crosses strip floor."""
        if total_dy < 0 and self._jobs_pane_compact:
            self._set_jobs_pane_compact(False)
            return True
        if (
            total_dy > 0
            and not self._jobs_pane_compact
            and self._jobs_strip_compact_available()
            and start_sizes
            and len(start_sizes) > 2
        ):
            compact = self._jobs_compact_pane_height()
            projected_jobs_h = start_sizes[2] - total_dy
            if projected_jobs_h <= compact + 1:
                self._set_jobs_pane_compact(True)
                self._enforce_jobs_compact_splitter_size()
                return True
        return False

    def _jobs_pane_drag_after(self, total_dy: int) -> None:
        """Enter compact when shrunk to the strip floor; ignore smaller sizes."""
        if total_dy <= 0:
            return
        self._sync_jobs_compact_from_splitter_size()

    def _sync_jobs_compact_from_splitter_size(self) -> None:
        if not self._jobs_strip_compact_available():
            if self._jobs_pane_compact:
                self._set_jobs_pane_compact(False)
            return
        sizes = self.splitter.sizes()
        if len(sizes) < 3:
            return
        compact = self._jobs_compact_pane_height()
        jobs_h = sizes[2]
        if jobs_h <= compact + 1:
            if not self._jobs_pane_compact:
                self._set_jobs_pane_compact(True)
            self._enforce_jobs_compact_splitter_size()
        elif self._jobs_pane_compact and jobs_h > compact + 1:
            self._set_jobs_pane_compact(False)

    def _maybe_restore_jobs_compact_from_sizes(self) -> None:
        """Legacy sessions saved compact height without the compact flag."""
        if self._jobs_pane_compact or not self._jobs_strip_compact_available():
            return
        sizes = self.splitter.sizes()
        if len(sizes) > 2 and sizes[2] <= self._jobs_compact_pane_height() + 1:
            self._set_jobs_pane_compact(True)
            self._enforce_jobs_compact_splitter_size()

    def _pane_visibility(self) -> list[bool]:
        jobs_vis = self.jobs_visible if self._jobs_feature_enabled else False
        return [self.shortcuts_visible, self.information_visible, jobs_vis]

    def _header_height_for_pane(self, pane_idx: int) -> int:
        if pane_idx == 0 and self.shortcuts_header:
            return self.shortcuts_header.height()
        if pane_idx == 1 and self.information_widget and self.information_widget.information_header:
            return self.information_widget.information_header.height()
        if pane_idx == 2 and self.jobs_header:
            return self.jobs_header.height()
        return 30

    def _pane_min_height(self, pane_idx: int, *, header_only: bool = False) -> int:
        """Minimum splitter height so a pane's title bar stays visible."""
        if not self._pane_visibility()[pane_idx]:
            return 0
        if pane_idx == 2 and not header_only and self._jobs_pane_compact:
            return self._jobs_compact_pane_height()
        if pane_idx == 1 and not header_only:
            return self._header_height_for_pane(1) + MIN_INFORMATION_CONTENT_HEIGHT
        return pane_min_height(
            self._header_height_for_pane(pane_idx), header_only=header_only
        )

    def _jobs_compact_pane_height(self) -> int:
        header_h = self._header_height_for_pane(2)
        if not self.jobs_visible or self.jobs_widget is None:
            return header_h
        return header_h + self.jobs_widget.compact_content_height()

    def _set_jobs_pane_compact(self, compact: bool, *, persist: bool = True) -> None:
        compact = bool(compact)
        if compact == self._jobs_pane_compact:
            if compact:
                self._sync_jobs_compact_geometry()
            return
        self._jobs_pane_compact = compact
        if self.jobs_widget is not None:
            self.jobs_widget.set_queue_compact(compact)
            self.jobs_widget.updateGeometry()
        if self.jobs_content is None:
            if persist and self._jobs_feature_enabled:
                self.main_window.config.update_setting('jobs_pane_compact', compact)
            return
        if compact:
            self._sync_jobs_compact_geometry()
        else:
            self.jobs_content.setMinimumHeight(0)
            self.jobs_content.setMaximumHeight(16777215)
            self.jobs_content.setSizePolicy(
                QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
            )
        if persist and self._jobs_feature_enabled:
            self.main_window.config.update_setting('jobs_pane_compact', compact)

    def _sync_jobs_compact_geometry(self) -> None:
        """Pin jobs content and splitter to the progress strip height."""
        if not self._jobs_pane_compact or self.jobs_widget is None:
            return
        strip_h = self.jobs_widget.compact_content_height()
        self.jobs_widget.refresh_compact_geometry(strip_h)
        if self.jobs_content is not None:
            self.jobs_content.setSizePolicy(
                QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
            )
            self.jobs_content.setFixedHeight(strip_h)
        self._enforce_jobs_compact_splitter_size()

    def _enforce_jobs_compact_splitter_size(self) -> None:
        """Keep the jobs splitter slice at header + strip when minimized."""
        if not self._jobs_pane_compact or not self._pane_visibility()[2]:
            return
        compact = self._jobs_compact_pane_height()
        sizes = list(self.splitter.sizes())
        if len(sizes) < 3 or sizes[2] == compact:
            return
        delta = sizes[2] - compact
        sizes[2] = compact
        if delta > 0:
            if sizes[1] > 0:
                sizes[1] += delta
            elif sizes[0] > 0:
                sizes[0] += delta
        else:
            need = -delta
            for idx in (1, 0):
                if need <= 0:
                    break
                min_h = self._pane_min_height(idx)
                take = min(max(0, sizes[idx] - min_h), need)
                sizes[idx] -= take
                need -= take
        self._set_splitter_sizes_safe(sizes)

    def _set_splitter_sizes_safe(self, sizes: list[int]) -> None:
        self._adjusting_splitter = True
        try:
            self.splitter.setSizes(sizes)
        finally:
            self._adjusting_splitter = False

    def _ensure_pane_headers_visible(
        self, collapse_header_only: dict[int, bool] | None = None
    ) -> bool:
        """Keep every visible pane tall enough to show its title bar."""
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

    def _needed_pane_height(self, pane_idx: int) -> int:
        header_h = self._header_height_for_pane(pane_idx)
        if pane_idx == 0 and self.shortcuts_widget:
            return header_h + self.shortcuts_widget.preferred_content_height()
        if pane_idx == 1 and self.information_widget:
            return header_h + self.information_widget.preferred_content_height()
        if pane_idx == 2 and self.jobs_widget:
            return header_h + self.jobs_widget.preferred_content_height()
        return header_h + MIN_PANE_CONTENT

    def _prepare_pane_measure(self, pane_idx: int) -> None:
        """Flush layout so fit-to-content height measurements are stable."""
        if pane_idx == 0 and self.shortcuts_widget:
            self.shortcuts_widget.content_widget.adjustSize()
        if pane_idx == 1 and self.information_widget:
            iw = self.information_widget
            w = iw.width()
            if iw.info_text_edit and w > 0:
                iw.info_text_edit.document().setTextWidth(w - 36)
                iw.info_text_edit.updateGeometry()
        if pane_idx == 2 and self.jobs_widget is not None:
            self.jobs_widget._refresh_active_job_strip(force=True)
            self.jobs_widget._reflow_all()
        QApplication.processEvents(QEventLoop.ProcessEventsFlag.ExcludeUserInputEvents)

    def _pane_size_at_fit_target(self, pane_idx: int, current: int, needed: int) -> bool:
        return pane_height_at_target(
            current,
            needed,
            stored_target=self._pane_fit_targets.get(pane_idx),
        )

    def _collapse_pane_from_fit(self, pane_idx: int) -> None:
        if pane_idx == 2 and self._jobs_strip_compact_available():
            compact = self._jobs_compact_pane_height()
            self._set_jobs_pane_compact(True)
            self._resize_pane_to_height(2, compact)
            self._sync_jobs_compact_geometry()
            return
        if pane_idx == 2:
            self._set_jobs_pane_compact(False)
        self._resize_pane_to_height(pane_idx, self._pane_min_height(pane_idx))

    def _expand_pane_to_fit_stabilized(self, pane_idx: int) -> None:
        """Resize to fit content; re-measure until height stabilizes."""
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
        """Double-click: expand to fit content, or collapse if already at fit."""
        if pane_idx == 0 and not self.shortcuts_visible:
            self.set_shortcuts_visible(True)
        elif pane_idx == 1 and not self.information_visible:
            self.set_information_visible(True)
        elif pane_idx == 2 and not self.jobs_visible:
            self.set_jobs_visible(True)

        vis = self._pane_visibility()
        if not vis[pane_idx]:
            return

        if pane_idx == 2 and self._jobs_pane_compact:
            self._set_jobs_pane_compact(False)
            self._expand_pane_to_fit_stabilized(2)
            return

        self._prepare_pane_measure(pane_idx)
        needed = self._needed_pane_height(pane_idx)
        sizes = self.splitter.sizes()
        current = sizes[pane_idx] if pane_idx < len(sizes) else 0

        if self._pane_size_at_fit_target(pane_idx, current, needed):
            self._collapse_pane_from_fit(pane_idx)
            self._pane_fit_targets.pop(pane_idx, None)
        else:
            if pane_idx == 2:
                self._set_jobs_pane_compact(False)
            self._expand_pane_to_fit_stabilized(pane_idx)

    def _resize_pane_to_height(self, pane_idx: int, target_height: int) -> None:
        """Resize one pane to *target_height*; shrink neighbors only as needed."""
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
        if pane_idx == 2 and self._jobs_pane_compact:
            self._sync_jobs_compact_geometry()
        self._persist_splitter_sizes()

    def _persist_splitter_sizes(self) -> None:
        """Merge current splitter sizes for visible panes into saved settings."""
        vis = self._pane_visibility()
        sizes = self.splitter.sizes()
        if len(sizes) != 3:
            return
        saved = (
            list(self.saved_splitter_sizes)
            if isinstance(self.saved_splitter_sizes, list) and len(self.saved_splitter_sizes) == 3
            else [150, 250, 120]
        )
        for i in range(3):
            if vis[i] and sizes[i] > 0:
                saved[i] = sizes[i]
        self.saved_splitter_sizes = saved
        self.main_window.config.update_setting('shortcuts_splitter_sizes', saved)

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

    def _expand_shortcuts_pane_to_fit(self) -> None:
        self._toggle_pane_fit(0)

    def _expand_information_pane_to_fit(self) -> None:
        self._toggle_pane_fit(1)

    def _expand_jobs_pane_to_fit(self) -> None:
        self._toggle_pane_fit(2)

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
            want_compact = self._jobs_pane_compact and self._jobs_strip_compact_available()
            self._set_jobs_pane_compact(want_compact, persist=False)
            self.jobs_widget.show()
            if hasattr(self.jobs_widget, "attach_titlebar_tools"):
                self.jobs_widget.attach_titlebar_tools()
            if hasattr(self.jobs_widget, "refresh_header_status"):
                self.jobs_widget.refresh_header_status()

    def set_jobs_visible(self, visible):
        """Set Jobs visibility programmatically (e.g. from J key)"""
        if not self._jobs_feature_enabled:
            return
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
        if not self._jobs_feature_enabled:
            return False
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
                self._maybe_restore_jobs_compact_from_sizes()
                if self._jobs_pane_compact:
                    self._sync_jobs_compact_geometry()
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
        self._maybe_restore_jobs_compact_from_sizes()
        if self._jobs_pane_compact:
            self._sync_jobs_compact_geometry()

    def _on_splitter_moved(self):
        """Handle splitter resize - save sizes, update information text width, emit signal"""
        if not self._adjusting_splitter:
            self._pane_fit_targets.clear()
            self._sync_jobs_compact_from_splitter_size()
            self._ensure_pane_headers_visible()
        self._persist_splitter_sizes()
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
        new_h = event.size().height()
        if new_h > 0 and new_h != event.oldSize().height():
            self._update_splitter_sizes()
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
        pane_bg = th.sidebar_background_color_hex
        apply_sidebar_pane_background(self, pane_bg)
        self.setStyleSheet(th.right_sidebar_combined_stylesheet())
        self.splitter.setHandleWidth(th.view_border_width_px)
        apply_sidebar_pane_background(self.splitter, pane_bg)
        self.splitter.setStyleSheet(th.right_sidebar_inner_splitter_stylesheet())
        pane_ss = th.file_tree_pane_shell_stylesheet()
        for w in (
            getattr(self, "shortcuts_section", None),
            getattr(self, "jobs_section", None),
            getattr(self, "shortcuts_content", None),
            getattr(self, "jobs_content", None),
        ):
            if w is not None:
                apply_section_pane_shell(w, pane_bg, pane_ss)
        if getattr(self, "shortcuts_header", None):
            self.shortcuts_header.refresh_theme_styles()
        if getattr(self, "jobs_header", None):
            self.jobs_header.refresh_theme_styles()
        if self.shortcuts_widget:
            self.shortcuts_widget.refresh_theme_styles()
        if self.information_widget:
            self.information_widget.refresh_theme_styles()
        if self.jobs_widget and hasattr(self.jobs_widget, "refresh_theme_styles"):
            self.jobs_widget.refresh_theme_styles()
