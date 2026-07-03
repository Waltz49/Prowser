#!/usr/bin/env python3
"""Modeless dialog showing the image-generation job queue."""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QDialog,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
)

from imagegen_plugins.image_gen_persistence import (
    load_job_queue_geometry_hex,
    save_job_queue_geometry_hex,
)
from imagegen_plugins.job_queue_panel import (
    JobQueuePanelWidget,
    job_control_dialog_outer_minimum_width,
)
# Re-export shared helpers for existing importers.
from imagegen_plugins.job_queue_common import (  # noqa: F401
    _ACTION_COL_WIDTH,
    _apply_job_queue_cell_background,
    _valid_preview_paths,
    build_job_queue_action_widget,
    create_invalid_job_preview_label,
    info_html_for_queue_row,
    job_queue_cancel_row,
    job_queue_edit_row,
    open_reference_thumbnail_paths,
)
from theme.theme_service import get_active_theme
from thumbnails.combined_sidebar_widget import HeaderWidget
from utils import (
    _center_styled_dialog_on_screen,
    ensure_dialog_fits_screen,
    save_dialog_geometry_hex,
)

_DIALOG_MARGIN = 8
_NEAR_MAX_HEIGHT_TOLERANCE = 20


class ImageGenJobQueueDialog(QDialog):
    """Floating job control dialog — same cards and progress strip as the jobs pane."""

    def __init__(self, main_window, parent=None):
        super().__init__(parent or main_window)
        self.main_window = main_window
        self._geometry_restore_attempted = False
        self._geometry_was_restored = False
        self._maximized_height: int | None = None

        self.setWindowTitle("Job Control")
        self.setModal(False)
        self._sync_dialog_width_limits()
        self.setMinimumHeight(120)

        t = get_active_theme()
        self.setStyleSheet(
            f"""
            QDialog {{
                background-color: {t.dialog_background_hex};
                color: {t.dialog_text_color_hex};
            }}
            """
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            _DIALOG_MARGIN, _DIALOG_MARGIN, _DIALOG_MARGIN, _DIALOG_MARGIN
        )
        layout.setSpacing(0)

        self._header = HeaderWidget(
            "Job Control", omit_left_border=True, omit_right_border=True
        )
        self._header.hide_button.setText("×")
        self._header.hide_button.setToolTip("Close job control dialog")
        self._header.hide_button.clicked.connect(self.hide)
        self._header.title_double_clicked.connect(self._toggle_maximize_or_compact)
        layout.addWidget(self._header)

        self._panel = JobQueuePanelWidget(main_window, self)
        self._panel.set_header_getter(lambda: self._header)
        self._panel.set_on_compact_geometry_changed(self._sync_dialog_height_to_panel)
        self._panel.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        layout.addWidget(self._panel, 1)

        self._panel.attach_header_tools()

        empty_label = self._panel.empty_label_widget()

        def _on_empty_label_press(event) -> None:
            if (
                event.button() == Qt.MouseButton.LeftButton
                and self._is_empty_queue_state()
            ):
                self.hide()
                event.accept()
                return
            QLabel.mousePressEvent(empty_label, event)

        empty_label.mousePressEvent = _on_empty_label_press

        dismiss_shortcut = QShortcut(QKeySequence("Ctrl+J"), self)
        dismiss_shortcut.setContext(Qt.ShortcutContext.WindowShortcut)
        dismiss_shortcut.activated.connect(self.hide)

    def _is_empty_queue_state(self) -> bool:
        return not self._panel.is_queue_list_visible() and not self._panel.has_job_rows()

    def _sync_dialog_width_limits(self) -> None:
        self.setMinimumWidth(
            job_control_dialog_outer_minimum_width(margin_px=_DIALOG_MARGIN)
        )

    def _schedule_refresh_table(self) -> None:
        self._panel.schedule_refresh()

    def _layout_chrome_height(self) -> int:
        layout = self.layout()
        margins = layout.contentsMargins() if layout is not None else None
        margin_h = 0
        if margins is not None:
            margin_h = margins.top() + margins.bottom()
        return self._header.height() + margin_h

    def _max_screen_client_height(self) -> int:
        from utils import _resolve_screen_for_styled_dialog

        screen = _resolve_screen_for_styled_dialog(self.main_window)
        if screen is None:
            return self.height()
        ag = screen.availableGeometry()
        return max(self.minimumHeight(), ag.height() - 2 * _DIALOG_MARGIN)

    def _content_height_for_mode(self, *, compact: bool) -> int:
        if compact:
            panel_h = self._panel.compact_content_height()
            if panel_h <= 0 and not self._panel.has_job_rows():
                panel_h = self._panel.empty_state_height_hint()
        else:
            panel_h = self._panel.preferred_content_height()
        return self._layout_chrome_height() + panel_h

    def _sync_dialog_height_to_panel(self) -> None:
        if not self.isVisible():
            return
        target = self._content_height_for_mode(
            compact=self._panel.is_queue_compact()
        )
        target = max(self.minimumHeight(), target)
        self.resize(self.width(), target)
        ensure_dialog_fits_screen(self, self.main_window, margin=_DIALOG_MARGIN)

    def _is_near_maximized_height(self) -> bool:
        max_h = self._maximized_height
        if max_h is None:
            max_h = self._max_screen_client_height()
        return abs(self.height() - max_h) <= _NEAR_MAX_HEIGHT_TOLERANCE

    def _toggle_maximize_or_compact(self) -> None:
        if self._is_near_maximized_height():
            self._panel.set_queue_compact(True)
            self._sync_dialog_height_to_panel()
            return
        self._panel.set_queue_compact(False)
        self._panel.prepare_expand_layout()
        needed = self._content_height_for_mode(compact=False)
        max_h = self._max_screen_client_height()
        self._maximized_height = max_h
        target = min(needed, max_h)
        self.resize(self.width(), max(self.minimumHeight(), target))
        ensure_dialog_fits_screen(self, self.main_window, margin=_DIALOG_MARGIN)

    def _save_geometry(self) -> None:
        try:
            save_job_queue_geometry_hex(save_dialog_geometry_hex(self))
        except Exception:
            pass

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._is_empty_queue_state():
            self.hide()
            event.accept()
            return
        super().mousePressEvent(event)

    def closeEvent(self, event) -> None:
        self._save_geometry()
        event.ignore()
        self.hide()

    def hideEvent(self, event) -> None:
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
        if not self._geometry_was_restored:
            QTimer.singleShot(
                0, lambda: _center_styled_dialog_on_screen(self, self.main_window)
            )
        self._panel.set_queue_compact(False)
        self._sync_dialog_width_limits()
        self._schedule_refresh_table()
        self._panel.refresh_header_status()


def open_imagegen_job_queue_dialog(main_window) -> None:
    """Show the full job queue dialog (does not toggle hide)."""
    dlg = getattr(main_window, "_imagegen_job_queue_dialog", None)
    if dlg is None:
        dlg = ImageGenJobQueueDialog(main_window)
        main_window._imagegen_job_queue_dialog = dlg
    from utils import present_auxiliary_dialog

    dlg._schedule_refresh_table()
    present_auxiliary_dialog(dlg)


def show_imagegen_job_queue_dialog(main_window) -> None:
    dlg = getattr(main_window, "_imagegen_job_queue_dialog", None)
    if dlg is None:
        dlg = ImageGenJobQueueDialog(main_window)
        main_window._imagegen_job_queue_dialog = dlg
    if dlg.isVisible():
        dlg.hide()
        return
    open_imagegen_job_queue_dialog(main_window)
