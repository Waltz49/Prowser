#!/usr/bin/env python3
"""Modeless dialog showing the image-generation job queue."""

from __future__ import annotations

import os

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from imagegen_plugins.image_gen_controller import get_imagegen_controller
from imagegen_plugins.job_prompt_tooltip import (
    install_delayed_prompt_tooltip,
    notify_job_prompt_tooltip_content_updating,
)
from imagegen_plugins.image_gen_persistence import (
    load_job_queue_geometry_hex,
    save_job_queue_geometry_hex,
)
from status_bar_config import (
    _apply_task_info_html_to_browser,
    configure_task_info_text_browser,
)
from theme_base import asset_path
from theme_service import get_active_theme
from utils import (
    _center_styled_dialog_on_screen,
    create_dialog_thumbnail_label,
    restore_dialog_geometry_hex,
    save_dialog_geometry_hex,
    show_styled_critical,
    show_styled_question,
    show_styled_warning,
)

_THUMB_SIZE = 72
_ROW_PAD = 12


def _job_queue_app_background_hex() -> str:
    return get_active_theme().default_background_color_hex


def _job_queue_cell_background_stylesheet() -> str:
    bg = _job_queue_app_background_hex()
    return f"background-color: {bg};"


def _job_queue_table_stylesheet() -> str:
    t = get_active_theme()
    bg = t.default_background_color_hex
    return f"""
            QTableWidget {{
                background-color: {bg};
                color: {t.dialog_text_color_hex};
                border: 1px solid {t.border_default_hex};
                gridline-color: {t.border_default_hex};
                alternate-background-color: {bg};
            }}
            QTableWidget::item {{
                background-color: {bg};
                padding: 4px;
            }}
            QTableCornerButton::section {{
                background-color: {bg};
                border: 1px solid {t.border_default_hex};
            }}
            QHeaderView::section {{
                background-color: {bg};
                color: {t.dialog_text_color_hex};
                border: 1px solid {t.border_default_hex};
                padding: 4px;
            }}
            """


def _apply_job_queue_cell_background(widget: QWidget) -> None:
    widget.setStyleSheet(_job_queue_cell_background_stylesheet())
    widget.setAutoFillBackground(True)


def _open_image_in_browse(main_window, file_path: str) -> None:
    path = (file_path or "").strip()
    if not path or not os.path.isfile(path):
        show_styled_warning(
            main_window,
            "Invalid File",
            f"File does not exist: {path or '(unknown)'}",
        )
        return
    try:
        if hasattr(main_window, "set_date_sort"):
            main_window.set_date_sort(reverse=False, notify=False)
        loader = getattr(main_window, "load_file_with_directory_thumbnails", None)
        if loader is None:
            show_styled_warning(
                main_window,
                "Cannot open image",
                "Browse view is not available.",
            )
            return
        loader(path)
    except Exception as e:
        show_styled_critical(main_window, "Cannot open image", str(e))


def _make_clickable_thumbnail(main_window, file_path: str, size: int) -> QLabel:
    thumb = create_dialog_thumbnail_label(file_path, size)
    thumb.setCursor(Qt.CursorShape.PointingHandCursor)
    thumb.setToolTip("Click to open in browse mode")

    def _on_mouse_press(event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            _open_image_in_browse(main_window, file_path)

    thumb.mousePressEvent = _on_mouse_press
    return thumb


def _info_content_width(table: QTableWidget) -> int:
    viewport_w = table.viewport().width()
    if viewport_w < 80:
        viewport_w = max(520, table.width()) - 48
    return max(240, viewport_w - _THUMB_SIZE - 36 - 48)


def _apply_info_browser_html(
    info_browser: QTextBrowser, body_html: str, *, content_width: int
) -> int:
    if not body_html:
        return info_browser.height()
    return _apply_task_info_html_to_browser(
        info_browser, body_html, content_width=content_width
    )


def _trash_button_stylesheet() -> str:
    t = get_active_theme()
    trash_url = f"url({asset_path('trash_icon.svg')})"
    trash_hover_url = f"url({asset_path('trash_icon_hover.svg')})"
    return f"""
        QPushButton {{
            background-color: {t.dialog_background_hex};
            border: 1px solid {t.border_default_hex};
            border-radius: 3px;
            padding: 0px;
            min-width: 22px;
            max-width: 22px;
            min-height: 22px;
            max-height: 22px;
            image: {trash_url};
        }}
        QPushButton:focus {{
            border: 1px solid {t.current_image_border_color_hex};
            outline: none;
        }}
        QPushButton:hover {{
            background-color: {t.tab_button_hover_bg_hex};
            border: 1px solid {t.tab_button_hover_bg_hex};
            image: {trash_hover_url};
        }}
        QPushButton:pressed {{
            background-color: {t.sidebar_splitter_handle_hex};
        }}
    """


class ImageGenJobQueueDialog(QDialog):
    """Scrollable table of active and queued image-generation jobs."""

    def __init__(self, main_window, parent=None):
        super().__init__(parent or main_window)
        self.main_window = main_window
        self._controller = get_imagegen_controller(main_window)
        self._refresh_timer: QTimer | None = None
        self._signal_connected = False
        self._geometry_restore_attempted = False
        self._geometry_was_restored = False

        self.setWindowTitle("Job Queue")
        self.setModal(False)
        self.setMinimumWidth(520)
        self.setMinimumHeight(280)
        self.resize(560, 360)

        t = get_active_theme()
        self.setStyleSheet(
            f"""
            QDialog {{
                background-color: {t.dialog_background_hex};
                color: {t.dialog_text_color_hex};
            }}
            {_job_queue_table_stylesheet()}
            """
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        self._empty_label = QLabel("No jobs in the queue.")
        self._empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_label.setStyleSheet(
            f"color: {t.dialog_text_color_hex}; font-size: 13px; padding: 24px;"
        )

        def _on_empty_label_press(event) -> None:
            if (
                event.button() == Qt.MouseButton.LeftButton
                and not self._table.isVisible()
            ):
                self.hide()
                event.accept()
                return
            QLabel.mousePressEvent(self._empty_label, event)

        self._empty_label.mousePressEvent = _on_empty_label_press
        layout.addWidget(self._empty_label)

        self._table = QTableWidget(0, 3, self)
        self._table.setHorizontalHeaderLabels(["", "Job", "Preview"])
        self._table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Fixed
        )
        self._table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch
        )
        self._table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.Fixed
        )
        self._table.setColumnWidth(0, 36)
        self._table.setColumnWidth(2, _THUMB_SIZE + 24)
        self._table.verticalHeader().setVisible(False)
        self._table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setAlternatingRowColors(False)
        self._table.setShowGrid(True)
        self._table.viewport().setAutoFillBackground(True)
        self._table.viewport().setStyleSheet(_job_queue_cell_background_stylesheet())
        layout.addWidget(self._table, 1)

        dismiss_shortcut = QShortcut(QKeySequence("Ctrl+J"), self)
        dismiss_shortcut.setContext(Qt.ShortcutContext.WindowShortcut)
        dismiss_shortcut.activated.connect(self.hide)

        self._connect_controller()
        self.refresh_table()

    def _save_geometry(self) -> None:
        try:
            save_job_queue_geometry_hex(save_dialog_geometry_hex(self))
        except Exception:
            pass

    def _connect_controller(self) -> None:
        if self._signal_connected:
            return
        self._controller.queue_changed.connect(self.refresh_table)
        self._controller.task_status_info_changed.connect(self._refresh_active_row_info)
        self._signal_connected = True
        timer = QTimer(self)
        timer.setInterval(500)
        timer.timeout.connect(self._refresh_active_row_info)
        timer.start()
        self._refresh_timer = timer

    def mousePressEvent(self, event) -> None:
        if (
            event.button() == Qt.MouseButton.LeftButton
            and not self._table.isVisible()
        ):
            self.hide()
            event.accept()
            return
        super().mousePressEvent(event)

    def closeEvent(self, event) -> None:
        self._save_geometry()
        if self._refresh_timer is not None:
            self._refresh_timer.stop()
        event.ignore()
        self.hide()

    def hideEvent(self, event) -> None:
        self._save_geometry()
        if self._refresh_timer is not None:
            self._refresh_timer.stop()
        super().hideEvent(event)

    def showEvent(self, event) -> None:
        if not self._geometry_restore_attempted:
            self._geometry_restore_attempted = True
            try:
                geom_hex = load_job_queue_geometry_hex()
                if geom_hex:
                    self._geometry_was_restored = restore_dialog_geometry_hex(
                        self, geom_hex, self.main_window
                    )
            except Exception:
                pass
        super().showEvent(event)
        if not self._geometry_was_restored:
            QTimer.singleShot(
                0, lambda: _center_styled_dialog_on_screen(self, self.main_window)
            )
        if self._refresh_timer is not None:
            self._refresh_timer.start()
        self.refresh_table()

    def _refresh_active_row_info(self) -> None:
        if not self.isVisible():
            return
        rows = self._controller.queue_snapshot()
        if not rows or not rows[0].is_active:
            return
        browser = self._table.cellWidget(0, 1)
        if isinstance(browser, QTextBrowser):
            info_html = self._controller.get_task_queue_status_info_html()
            if info_html:
                notify_job_prompt_tooltip_content_updating(browser)
                content_width = _info_content_width(self._table)
                browser_h = _apply_info_browser_html(
                    browser, info_html, content_width=content_width
                )
                row_h = max(_THUMB_SIZE + _ROW_PAD, browser_h + _ROW_PAD)
                self._table.setRowHeight(0, row_h)

    def refresh_table(self) -> None:
        rows = self._controller.queue_snapshot()
        has_rows = bool(rows)
        self._empty_label.setVisible(not has_rows)
        self._table.setVisible(has_rows)
        layout = self.layout()
        if layout is not None:
            layout.setStretchFactor(self._empty_label, 1 if not has_rows else 0)
            layout.setStretchFactor(self._table, 1 if has_rows else 0)
        self._table.setRowCount(len(rows))
        content_width = _info_content_width(self._table)

        for row_idx, row in enumerate(rows):
            cancel_btn = QPushButton()
            cancel_btn.setToolTip("Cancel job")
            cancel_btn.setStyleSheet(_trash_button_stylesheet())
            cancel_btn.clicked.connect(
                lambda _checked=False, r=row_idx: self._on_cancel_row(r)
            )
            cancel_wrap = QWidget()
            _apply_job_queue_cell_background(cancel_wrap)
            cancel_layout = QHBoxLayout(cancel_wrap)
            cancel_layout.setContentsMargins(4, 0, 4, 0)
            cancel_layout.addWidget(cancel_btn, alignment=Qt.AlignmentFlag.AlignCenter)
            self._table.setCellWidget(row_idx, 0, cancel_wrap)

            info_browser = QTextBrowser()
            configure_task_info_text_browser(
                info_browser, self.main_window, job_queue_cell=True
            )
            info_html = (
                self._controller.get_task_queue_status_info_html()
                if row.is_active
                else row.status_html
            )
            browser_h = _apply_info_browser_html(
                info_browser, info_html or "", content_width=content_width
            )
            install_delayed_prompt_tooltip(info_browser, row.full_prompt)
            self._table.setCellWidget(row_idx, 1, info_browser)

            preview_wrap = QWidget()
            _apply_job_queue_cell_background(preview_wrap)
            preview_layout = QHBoxLayout(preview_wrap)
            preview_layout.setContentsMargins(4, 4, 4, 4)
            preview_layout.setSpacing(6)
            paths = row.thumbnail_paths[:2]
            if paths:
                for path in paths:
                    preview_layout.addWidget(
                        _make_clickable_thumbnail(
                            self.main_window, path, _THUMB_SIZE
                        ),
                        alignment=Qt.AlignmentFlag.AlignCenter,
                    )
            else:
                placeholder = QLabel("—")
                placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
                placeholder.setFixedSize(_THUMB_SIZE, _THUMB_SIZE)
                _apply_job_queue_cell_background(placeholder)
                preview_layout.addWidget(placeholder)
            preview_layout.addStretch()
            self._table.setCellWidget(row_idx, 2, preview_wrap)

            row_h = max(_THUMB_SIZE + _ROW_PAD, browser_h + _ROW_PAD)
            self._table.setRowHeight(row_idx, row_h)

    def _on_cancel_row(self, row: int) -> None:
        rows = self._controller.queue_snapshot()
        if row < 0 or row >= len(rows):
            return
        entry = rows[row]
        if entry.is_active:
            prompt = "Cancel the running job?"
        else:
            prompt = "Remove this job from the queue?"
        answer = show_styled_question(
            self,
            "Cancel job?",
            prompt,
            default_no=True,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._controller.cancel_job_at_row(row)


def show_imagegen_job_queue_dialog(main_window) -> None:
    dlg = getattr(main_window, "_imagegen_job_queue_dialog", None)
    if dlg is None:
        dlg = ImageGenJobQueueDialog(main_window)
        main_window._imagegen_job_queue_dialog = dlg
    if dlg.isVisible():
        dlg.hide()
        return
    dlg.refresh_table()
    dlg.show()
    dlg.raise_()
    dlg.activateWindow()
