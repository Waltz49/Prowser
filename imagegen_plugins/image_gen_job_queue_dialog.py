#!/usr/bin/env python3
"""Modeless dialog showing the image-generation job queue."""

from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtGui import QKeyEvent, QCursor, QWindow
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from imagegen_plugins.image_gen_persistence import (
    load_job_queue_always_on_top,
    load_job_queue_geometry_hex,
    load_job_queue_size_mode,
    save_job_queue_always_on_top,
    save_job_queue_geometry_hex,
    save_job_queue_size_mode,
)
from imagegen_plugins.job_queue_panel import (
    JobQueuePanelWidget,
    QUEUE_SIZE_ALL,
    QUEUE_SIZE_ONE,
    QUEUE_SIZE_STRIP,
    job_control_dialog_outer_minimum_width,
)
from thumbnails.combined_sidebar_widget import HeaderWidget
import thumbnails.thumbnail_constants as tc
from theme.theme_service import get_active_theme
from thumbnails.sidebar_pane_layout import MIN_JOBS_QUEUE_CONTENT_HEIGHT, pane_fit_height_tolerance
from utils import (
    _center_styled_dialog_on_screen,
    apply_macos_frameless_floating_dialog,
    frameless_resize_cursor_for_pos,
    present_passive_floating_dialog,
    raise_passive_floating_dialog,
    save_dialog_geometry_hex,
    try_start_frameless_system_resize,
)

_DIALOG_BORDER_PX = 1
_SCREEN_EDGE_MARGIN = 8
_JOB_QUEUE_DIALOG_OBJECT_NAME = "jobQueueFloatingDialog"


def _is_cmd_j(event: QKeyEvent) -> bool:
    mods = event.modifiers() & ~Qt.KeyboardModifier.KeypadModifier
    cmd_pressed = bool(
        mods & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.MetaModifier)
    )
    other_mods = mods & ~(
        Qt.KeyboardModifier.ControlModifier
        | Qt.KeyboardModifier.MetaModifier
        | Qt.KeyboardModifier.ShiftModifier
        | Qt.KeyboardModifier.AltModifier
    )
    return (
        event.key() == Qt.Key.Key_J
        and cmd_pressed
        and (other_mods == Qt.KeyboardModifier.NoModifier or other_mods == 0)
    )


class _JobQueueKeyPassthroughFilter(QObject):
    """Forward keys to the main window when the dialog is active; keep Cmd+J to hide."""

    def __init__(self, dialog: "ImageGenJobQueueDialog") -> None:
        super().__init__(dialog)
        self._dialog = dialog

    def _watched_belongs_to_dialog(self, watched: QObject) -> bool:
        if watched is self._dialog:
            return True
        if isinstance(watched, QWidget):
            return self._dialog.isAncestorOf(watched)
        if isinstance(watched, QWindow):
            return watched is self._dialog.windowHandle()
        return False

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if event.type() != QEvent.Type.KeyPress:
            return False
        if not self._dialog.isVisible() or not self._dialog.isActiveWindow():
            return False
        if not self._watched_belongs_to_dialog(watched):
            return False
        key_event = event  # type: ignore[assignment]
        if _is_cmd_j(key_event):
            from imagegen_plugins.jobs_display_mode import toggle_jobs_panel

            toggle_jobs_panel(self._dialog.main_window)
            key_event.accept()
            return True
        main_window = self._dialog.main_window
        if main_window is not None and hasattr(main_window, "keyPressEvent"):
            main_window.keyPressEvent(key_event)
            return True
        return False


def _job_queue_floating_shell_stylesheet(*, strip_mode: bool = False) -> str:
    """1px sidebar-pane border; background matches jobs pane."""
    th = get_active_theme()
    border_hex = tc.SIDEBAR_HEADER_BORDER_HEX or th.sidebar_header_border_hex
    if strip_mode:
        border_css = f"{_DIALOG_BORDER_PX}px solid transparent"
    else:
        border_css = f"{_DIALOG_BORDER_PX}px solid {border_hex}"
    bg_hex = th.sidebar_background_color_hex
    text_hex = th.sidebar_text_color_hex
    return f"""
    #{_JOB_QUEUE_DIALOG_OBJECT_NAME} {{
        background-color: {bg_hex};
        border: {border_css};
        border-radius: 3px;
    }}
    #{_JOB_QUEUE_DIALOG_OBJECT_NAME} QWidget {{
        background-color: {bg_hex};
        color: {text_hex};
    }}
    """


class ImageGenJobQueueDialog(QDialog):
    """Floating job control dialog — same cards and progress strip as the jobs pane."""

    def __init__(self, main_window, parent=None):
        super().__init__(parent or main_window)
        self.main_window = main_window
        self._geometry_restore_attempted = False
        self._geometry_was_restored = False
        self._pending_initial_center = False
        self._restore_size_mode_pending = False
        self._syncing_shell_geometry = False
        self._always_on_top = load_job_queue_always_on_top()
        self._quit_shutdown = False

        self.setWindowTitle("Job Control")
        self.setModal(False)
        apply_macos_frameless_floating_dialog(self, always_on_top=self._always_on_top)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._key_passthrough_filter: _JobQueueKeyPassthroughFilter | None = None
        self._key_passthrough_filter_installed = False
        self.setMouseTracking(True)
        self._sync_dialog_width_limits()

        self.setObjectName(_JOB_QUEUE_DIALOG_OBJECT_NAME)
        self.setStyleSheet(_job_queue_floating_shell_stylesheet())

        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            _DIALOG_BORDER_PX,
            _DIALOG_BORDER_PX,
            _DIALOG_BORDER_PX,
            _DIALOG_BORDER_PX,
        )
        layout.setSpacing(0)
        self._shell_layout = layout

        self._header = HeaderWidget(
            "Job Control",
            omit_left_border=True,
            omit_right_border=True,
            omit_top_border=True,
        )
        self._header.set_hide_button_mode("close")
        self._header.hide_button.setToolTip("Close job control dialog")
        self._header.hide_button.clicked.connect(self._close_to_pane_mode)
        self._header.title_double_clicked.connect(self._cycle_header_size)
        self._header.configure_floating_window_move(self)
        layout.addWidget(self._header)

        self._panel = JobQueuePanelWidget(
            main_window, self, job_control_dialog=True
        )
        self._panel.set_header_getter(lambda: self._header)
        self._panel.set_on_compact_geometry_changed(self._on_panel_geometry_changed)
        self._panel.configure_floating_window_move(
            self,
            drag_via_client_getter=lambda: not self._header.isVisible(),
            double_click_callback=self._cycle_header_size,
        )
        self._panel.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        layout.addWidget(self._panel, 0)

        self._panel.attach_header_tools()

        empty_label = self._panel.empty_label_widget()

        def _on_empty_label_press(event) -> None:
            if (
                event.button() == Qt.MouseButton.LeftButton
                and self._is_empty_queue_state()
            ):
                self._close_to_pane_mode()
                event.accept()
                return
            QLabel.mousePressEvent(empty_label, event)

        empty_label.mousePressEvent = _on_empty_label_press

    def _install_key_passthrough_filter(self) -> None:
        if self._key_passthrough_filter_installed:
            return
        app = QApplication.instance()
        if app is None:
            return
        filt = self._key_passthrough_filter
        if filt is None:
            filt = _JobQueueKeyPassthroughFilter(self)
            self._key_passthrough_filter = filt
        app.installEventFilter(filt)
        self._key_passthrough_filter_installed = True

    def _remove_key_passthrough_filter(self) -> None:
        if not self._key_passthrough_filter_installed:
            return
        filt = self._key_passthrough_filter
        app = QApplication.instance()
        if filt is None or app is None:
            return
        app.removeEventFilter(filt)
        self._key_passthrough_filter_installed = False

    def _restore_main_window_keyboard_focus(self) -> None:
        host = self.main_window
        if host is not None:
            host.activateWindow()

    def is_job_queue_always_on_top(self) -> bool:
        return self._always_on_top

    def set_job_queue_always_on_top(self, enabled: bool) -> None:
        enabled = bool(enabled)
        if enabled == self._always_on_top:
            return
        self._always_on_top = enabled
        save_job_queue_always_on_top(enabled)
        was_visible = self.isVisible()
        apply_macos_frameless_floating_dialog(self, always_on_top=enabled)
        if was_visible:
            self.show()
            raise_passive_floating_dialog(self)

    def _is_empty_queue_state(self) -> bool:
        return not self._panel.is_queue_list_visible() and not self._panel.has_job_rows()

    def _sync_dialog_width_limits(self) -> None:
        self.setMinimumWidth(
            job_control_dialog_outer_minimum_width(
                margin_px=_DIALOG_BORDER_PX * 2
            )
        )

    def _layout_chrome_height(self) -> int:
        layout = self._shell_layout
        margins = layout.contentsMargins()
        header_h = self._header.height() if self._header.isVisible() else 0
        return margins.top() + header_h + margins.bottom()

    def _titlebar_hidden_for_mode(self, mode: str) -> bool:
        """Strip-only view with live progress hides the dialog title bar."""
        return mode == QUEUE_SIZE_STRIP and self._panel.has_active_generation()

    def _sync_titlebar_visibility(self, mode: str) -> None:
        self._header.setVisible(not self._titlebar_hidden_for_mode(mode))

    def _refresh_shell_stylesheet(self, mode: str | None = None) -> None:
        if mode is None:
            mode = self._panel.queue_size_mode()
        self.setStyleSheet(
            _job_queue_floating_shell_stylesheet(strip_mode=(mode == QUEUE_SIZE_STRIP))
        )

    def _sync_shell_layout_for_mode(self, mode: str) -> None:
        self._refresh_shell_stylesheet(mode)
        self._sync_titlebar_visibility(mode)
        layout = self._shell_layout
        shrink = self._panel.should_shrink_wrap_client()
        fixed_height = mode != QUEUE_SIZE_ALL or shrink
        layout.setStretchFactor(self._panel, 0)
        if fixed_height:
            if mode == QUEUE_SIZE_ALL and shrink:
                panel_h = self._panel.empty_state_height_hint()
            else:
                panel_h = self._panel.content_height_for_size_mode(mode)
            self._panel.setSizePolicy(
                QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
            )
            self._panel.setFixedHeight(panel_h)
            self._panel.setMaximumHeight(panel_h)
            self.setMinimumHeight(max(48, self._layout_chrome_height() + panel_h))
        else:
            self._panel.setMinimumHeight(0)
            self._panel.setMaximumHeight(16777215)
            self._panel.setSizePolicy(
                QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
            )
            layout.setStretchFactor(self._panel, 1)
            self.setMinimumHeight(
                max(48, self._layout_chrome_height() + MIN_JOBS_QUEUE_CONTENT_HEIGHT)
            )

    def _max_screen_client_height(self) -> int:
        from utils import _resolve_screen_for_styled_dialog

        screen = _resolve_screen_for_styled_dialog(self.main_window)
        if screen is None:
            return self.height()
        ag = screen.availableGeometry()
        return max(self.minimumHeight(), ag.height() - 2 * _SCREEN_EDGE_MARGIN)

    def _dialog_height_for_panel_mode(self, mode: str) -> int:
        chrome = self._layout_chrome_height()
        if mode == QUEUE_SIZE_ALL:
            if self._panel.should_shrink_wrap_client():
                panel_h = self._panel.empty_state_height_hint()
            else:
                panel_h = self._panel.preferred_content_height()
                max_panel = max(0, self._max_screen_client_height() - chrome)
                panel_h = min(panel_h, max_panel)
        else:
            panel_h = self._panel.content_height_for_size_mode(mode)
        return max(self.minimumHeight(), chrome + panel_h)

    def _resize_anchored_bottom(
        self, target_height: int, *, anchor_bottom_y: int | None = None
    ) -> None:
        """Resize while keeping the window bottom edge fixed (clamp to screen)."""
        from utils import _resolve_screen_for_styled_dialog

        geo = self.geometry()
        width = geo.width()
        # Use exclusive bottom (y + height); QRect.bottom() is inclusive and drifts -1 each resize.
        # Capture anchor before layout/minimumHeight changes — Qt may grow the window downward first.
        bottom_y = (
            int(anchor_bottom_y)
            if anchor_bottom_y is not None
            else geo.y() + geo.height()
        )
        target_height = max(self.minimumHeight(), target_height)
        new_y = bottom_y - target_height

        screen = _resolve_screen_for_styled_dialog(self.main_window)
        if screen is not None:
            ag = screen.availableGeometry()
            max_bottom_y = ag.bottom() + 1 - _SCREEN_EDGE_MARGIN
            min_top = ag.top() + _SCREEN_EDGE_MARGIN
            if bottom_y > max_bottom_y:
                bottom_y = max_bottom_y
                new_y = bottom_y - target_height
            if new_y < min_top:
                new_y = min_top
                target_height = min(target_height, bottom_y - new_y)

        if new_y == geo.y() and target_height == geo.height():
            return

        self.setGeometry(geo.x(), new_y, width, target_height)

    def _effective_restored_size_mode(self, saved: str) -> str:
        if saved not in (QUEUE_SIZE_ALL, QUEUE_SIZE_ONE, QUEUE_SIZE_STRIP):
            return QUEUE_SIZE_ALL
        has_jobs = self._panel.has_job_rows()
        has_active = self._panel.has_active_generation()
        if not has_jobs and not has_active:
            return QUEUE_SIZE_ALL
        if saved == QUEUE_SIZE_STRIP and not has_active:
            return QUEUE_SIZE_ALL
        if saved == QUEUE_SIZE_ONE and not has_jobs:
            return QUEUE_SIZE_STRIP if has_active else QUEUE_SIZE_ALL
        return saved

    def _persist_size_mode(self) -> None:
        try:
            save_job_queue_size_mode(self._panel.queue_size_mode())
        except Exception:
            pass

    def _apply_dialog_size_mode(self, mode: str) -> None:
        anchor_bottom_y = self.geometry().y() + self.geometry().height()
        if mode == QUEUE_SIZE_ALL:
            self._panel.prepare_expand_layout()
        self._panel.set_queue_size_mode(mode)
        self._sync_shell_layout_for_mode(mode)

        prev_height = -1
        target_height = self.minimumHeight()
        for _ in range(4):
            self._panel.prepare_size_measure()
            self._sync_shell_layout_for_mode(mode)
            target_height = self._dialog_height_for_panel_mode(mode)
            if prev_height >= 0 and abs(target_height - prev_height) <= 1:
                break
            prev_height = target_height

        self._resize_anchored_bottom(target_height, anchor_bottom_y=anchor_bottom_y)
        self._persist_size_mode()

    def _heights_match(self, a: int, b: int) -> bool:
        ref = max(a, b, 1)
        return abs(a - b) <= pane_fit_height_tolerance(ref)

    def _resolve_next_cycle_mode(self, current: str) -> str:
        """Advance fit cycle; skip steps that would not change dialog height."""
        has_jobs = self._panel.has_job_rows()
        has_active = self._panel.has_active_generation()

        if not has_jobs and not has_active:
            return QUEUE_SIZE_ALL

        if current == QUEUE_SIZE_STRIP:
            return QUEUE_SIZE_ALL
        if current == QUEUE_SIZE_ONE:
            return QUEUE_SIZE_STRIP if has_active else QUEUE_SIZE_ALL

        self._panel.prepare_size_measure()
        current_h = self.height()
        if not has_jobs:
            return QUEUE_SIZE_STRIP if has_active else QUEUE_SIZE_ALL

        one_h = self._dialog_height_for_panel_mode(QUEUE_SIZE_ONE)
        if self._heights_match(current_h, one_h):
            return QUEUE_SIZE_STRIP if has_active else QUEUE_SIZE_ALL
        return QUEUE_SIZE_ONE

    def _cycle_header_size(self) -> None:
        if not self._panel.has_job_rows() and not self._panel.has_active_generation():
            if self._panel.queue_size_mode() != QUEUE_SIZE_ALL:
                self._apply_dialog_size_mode(QUEUE_SIZE_ALL)
            return
        next_mode = self._resolve_next_cycle_mode(self._panel.queue_size_mode())
        if next_mode == self._panel.queue_size_mode():
            return
        self._apply_dialog_size_mode(next_mode)

    def _on_panel_geometry_changed(self) -> None:
        if self._syncing_shell_geometry:
            return
        self._syncing_shell_geometry = True
        try:
            if self._restore_size_mode_pending:
                self._restore_size_mode_pending = False
                mode = self._effective_restored_size_mode(load_job_queue_size_mode())
                self._apply_dialog_size_mode(mode)
            else:
                self._sync_dialog_height_to_panel_impl()
            if not self._pending_initial_center:
                return
            self._pending_initial_center = False
            if not self._geometry_was_restored:
                _center_styled_dialog_on_screen(self, self.main_window)
        finally:
            self._syncing_shell_geometry = False

    def _sync_dialog_height_to_panel(self) -> None:
        if not self.isVisible() or self._syncing_shell_geometry:
            return
        self._syncing_shell_geometry = True
        try:
            self._sync_dialog_height_to_panel_impl()
        finally:
            self._syncing_shell_geometry = False

    def _sync_dialog_height_to_panel_impl(self) -> None:
        if not self.isVisible():
            return
        anchor_bottom_y = self.geometry().y() + self.geometry().height()
        mode = self._panel.queue_size_mode()
        shrink = self._panel.should_shrink_wrap_client()
        fixed_height = mode != QUEUE_SIZE_ALL or shrink
        if fixed_height:
            self._panel.prepare_size_measure()
        self._sync_shell_layout_for_mode(mode)
        if mode == QUEUE_SIZE_ALL and not shrink:
            chrome = self._layout_chrome_height()
            panel_h = self._panel.preferred_content_height()
            max_panel = max(0, self._max_screen_client_height() - chrome)
            panel_h = min(panel_h, max_panel)
            target = max(self.minimumHeight(), chrome + panel_h)
            if self._heights_match(self.height(), target) or self.height() > target:
                return
            self._panel.prepare_size_measure()
            self._sync_shell_layout_for_mode(mode)
            target = self._dialog_height_for_panel_mode(mode)
            if self._heights_match(self.height(), target) or self.height() > target:
                return
        else:
            target = self._dialog_height_for_panel_mode(mode)
        self._resize_anchored_bottom(target, anchor_bottom_y=anchor_bottom_y)

    def _schedule_refresh_table(self) -> None:
        self._panel.schedule_refresh()

    def _save_geometry(self) -> None:
        try:
            save_job_queue_geometry_hex(save_dialog_geometry_hex(self))
        except Exception:
            pass

    def _update_frameless_resize_cursor(self, pos) -> None:
        cursor = frameless_resize_cursor_for_pos(self, pos)
        if cursor is None:
            self.unsetCursor()
        else:
            self.setCursor(QCursor(cursor))

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            if try_start_frameless_system_resize(
                self, event.globalPosition().toPoint()
            ):
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        self._update_frameless_resize_cursor(event.position().toPoint())
        super().mouseMoveEvent(event)

    def leaveEvent(self, event) -> None:
        self.unsetCursor()
        super().leaveEvent(event)

    def _close_to_pane_mode(self) -> None:
        from imagegen_plugins.jobs_display_mode import show_jobs_pane

        show_jobs_pane(self.main_window)

    def shutdown_for_quit(self) -> None:
        """Permit real close and tear down before application exit."""
        if self._quit_shutdown:
            return
        self._quit_shutdown = True
        self._remove_key_passthrough_filter()
        try:
            self._persist_size_mode()
            self._save_geometry()
        except Exception:
            pass
        self.hide()
        self.setParent(None)
        self.deleteLater()

    def closeEvent(self, event) -> None:
        if self._quit_shutdown:
            super().closeEvent(event)
            return
        self._save_geometry()
        event.ignore()
        self.hide()

    def hideEvent(self, event) -> None:
        self._remove_key_passthrough_filter()
        self._persist_size_mode()
        self._save_geometry()
        super().hideEvent(event)

    def show(self):
        from utils import restore_dialog_geometry_before_first_show

        restore_dialog_geometry_before_first_show(
            self, load_job_queue_geometry_hex(), self.main_window
        )
        super().show()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._install_key_passthrough_filter()
        self._restore_main_window_keyboard_focus()
        self._pending_initial_center = not self._geometry_was_restored
        self._restore_size_mode_pending = True
        self._sync_dialog_width_limits()
        self._schedule_refresh_table()
        self._panel.refresh_header_status()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if _is_cmd_j(event):
            from imagegen_plugins.jobs_display_mode import toggle_jobs_panel

            toggle_jobs_panel(self.main_window)
            event.accept()
            return
        main_window = self.main_window
        if main_window is not None and hasattr(main_window, "keyPressEvent"):
            main_window.keyPressEvent(event)
            return
        super().keyPressEvent(event)


def dismiss_job_queue_dialog_for_quit(main_window) -> None:
    """Close the floating job panel during application shutdown."""
    dlg = getattr(main_window, "_imagegen_job_queue_dialog", None)
    if dlg is None:
        return
    if hasattr(dlg, "shutdown_for_quit"):
        dlg.shutdown_for_quit()
    else:
        dlg.hide()
    main_window._imagegen_job_queue_dialog = None


def open_imagegen_job_queue_dialog(main_window) -> None:
    """Show the full job queue dialog (does not toggle hide)."""
    dlg = getattr(main_window, "_imagegen_job_queue_dialog", None)
    if dlg is None:
        dlg = ImageGenJobQueueDialog(main_window)
        main_window._imagegen_job_queue_dialog = dlg
    present_passive_floating_dialog(dlg)


def show_imagegen_job_queue_dialog(main_window) -> None:
    from imagegen_plugins.jobs_display_mode import toggle_jobs_panel

    toggle_jobs_panel(main_window)
