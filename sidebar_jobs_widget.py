#!/usr/bin/env python3
"""Job queue list for the right combined sidebar Jobs pane (matches dialog data)."""

from __future__ import annotations

import os

from PySide6.QtCore import QEvent, Qt, QTimer, QSize
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from imagegen_plugins.image_gen_controller import get_imagegen_controller
from imagegen_plugins.image_gen_job_queue_dialog import (
    _ACTION_COL_WIDTH,
    _apply_job_queue_cell_background,
    _valid_preview_paths,
    build_job_queue_action_widget,
    info_html_for_queue_row,
    open_reference_thumbnail_paths,
)
from imagegen_plugins.job_prompt_tooltip import install_delayed_prompt_tooltip
from imagegen_plugins.model_task_status_info import strip_references_from_status_html
from status_bar_config import (
    _apply_task_info_html_to_browser,
    configure_task_info_text_browser,
)
from theme_service import get_active_theme
from utils import create_dialog_thumbnail_label

_THUMB_SIZE = 55
_THUMB_GAP = 14


def _disable_tab_focus(root: QWidget) -> None:
    """Keep job pane controls out of the keyboard tab order."""
    root.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    for child in root.findChildren(QWidget):
        child.setFocusPolicy(Qt.FocusPolicy.NoFocus)


def _job_card_stylesheet() -> str:
    t = get_active_theme()
    bg = t.default_background_color_hex
    return f"""
        QFrame#sidebarJobCard {{
            background-color: {bg};
            color: {t.dialog_text_color_hex};
            border: 1px solid {t.border_default_hex};
            border-radius: 4px;
        }}
    """


class _FlowReferenceThumbs(QWidget):
    """Reference thumbnails in right-aligned rows; wrap on resize."""

    def __init__(self, main_window, paths: list[str], parent=None):
        super().__init__(parent)
        self._main_window = main_window
        self._paths = _valid_preview_paths(paths)
        self._cells: list[QLabel] = []
        self._last_cols: int | None = None
        self._last_reflow_width = 0
        self._reflow_guard = False
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._outer = QVBoxLayout(self)
        self._outer.setContentsMargins(0, 2, 0, 0)
        self._outer.setSpacing(_THUMB_GAP)
        for path in self._paths:
            thumb = create_dialog_thumbnail_label(path, _THUMB_SIZE)
            thumb.setCursor(Qt.CursorShape.PointingHandCursor)
            thumb.setToolTip(os.path.basename(path))
            self._cells.append(thumb)
        if self._paths:
            self.show()
            self.reflow_to_width(max(_THUMB_SIZE * 2, 120))
        else:
            self.hide()
            self.setFixedHeight(0)
            self.setMaximumHeight(0)
            self.setMinimumHeight(0)
            self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)

    def _effective_reflow_width(self, width: int) -> int:
        if width > 0:
            return width
        parent = self.parentWidget()
        if parent is not None and parent.width() > 0:
            return parent.width()
        return max(_THUMB_SIZE * 2, 120)

    def _cols_for_width(self, width: int) -> int:
        w = max(width, _THUMB_SIZE)
        stride = _THUMB_SIZE + _THUMB_GAP
        return max(1, (w + _THUMB_GAP) // stride)

    def _content_height(self, cols: int) -> int:
        n = len(self._cells)
        if not n:
            return 0
        rows = (n + cols - 1) // cols
        return rows * (_THUMB_SIZE + _THUMB_GAP) - _THUMB_GAP + 4

    def _row_width(self, count: int) -> int:
        if count <= 0:
            return 0
        return count * _THUMB_SIZE + (count - 1) * _THUMB_GAP

    def _content_width(self, cols: int) -> int:
        n = len(self._cells)
        if not n:
            return 0
        first_row = min(cols, n)
        return self._row_width(first_row)

    def _clear_rows(self) -> None:
        while self._outer.count():
            item = self._outer.takeAt(0)
            row_layout = item.layout()
            if row_layout is not None:
                while row_layout.count():
                    row_layout.takeAt(0)
                row_layout.deleteLater()

    def reflow_to_width(self, width: int) -> None:
        width = self._effective_reflow_width(width)
        self._last_reflow_width = width
        if self._reflow_guard or not self._cells:
            return
        cols = self._cols_for_width(width)
        if cols == self._last_cols and self._outer.count() > 0:
            self._apply_thumb_height(cols, width)
            return
        self._reflow_guard = True
        try:
            self._clear_rows()
            self._last_cols = cols
            for row_start in range(0, len(self._cells), cols):
                row_layout = QHBoxLayout()
                row_layout.setContentsMargins(0, 0, 0, 0)
                row_layout.setSpacing(_THUMB_GAP)
                row_layout.addStretch(1)
                for cell in self._cells[row_start : row_start + cols]:
                    row_layout.addWidget(
                        cell,
                        0,
                        Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop,
                    )
                self._outer.addLayout(row_layout)
        finally:
            self._reflow_guard = False
        self._apply_thumb_height(cols, width)
        self.updateGeometry()

    def _apply_thumb_height(self, cols: int, width: int | None = None) -> None:
        flow_w = width or self._last_reflow_width or self._content_width(cols)
        w = max(flow_w, self._content_width(cols))
        h = self._content_height(cols)
        self.setMinimumWidth(w)
        self.setFixedHeight(h)
        self.setMinimumHeight(h)
        self.setMaximumHeight(h)

    def sizeHint(self) -> QSize:
        if not self._cells:
            return QSize(0, 0)
        cols = self._last_cols or self._cols_for_width(max(self.width(), _THUMB_SIZE))
        w = max(self._last_reflow_width, self._content_width(cols))
        return QSize(w, self._content_height(cols))

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._paths:
            open_reference_thumbnail_paths(self._main_window, self._paths)
            event.accept()
            return
        super().mousePressEvent(event)


class _JobCard(QFrame):
    """One queue row: action buttons | status HTML + thumbnails."""

    def __init__(
        self,
        main_window,
        controller,
        row_idx: int,
        *,
        is_active: bool,
        parent=None,
    ):
        super().__init__(parent)
        self.setObjectName("sidebarJobCard")
        self.setStyleSheet(_job_card_stylesheet())
        self._main_window = main_window
        self._controller = controller
        self._row_idx = row_idx
        self._full_prompt = ""
        self._last_info_html = ""

        row_layout = QHBoxLayout(self)
        row_layout.setContentsMargins(2, 2, 2, 2)
        row_layout.setSpacing(4)

        self._actions = build_job_queue_action_widget(
            main_window,
            controller,
            row_idx,
            is_active=is_active,
            parent=self,
        )
        row_layout.addWidget(self._actions, 0, Qt.AlignmentFlag.AlignTop)

        self._content = QWidget()
        _apply_job_queue_cell_background(self._content)
        content_layout = QVBoxLayout(self._content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(2)

        self._info_browser = QTextBrowser()
        configure_task_info_text_browser(
            self._info_browser, main_window, job_queue_cell=True
        )
        self._info_browser.setSizePolicy(
            QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed
        )

        self._refs = _FlowReferenceThumbs(main_window, [])
        content_layout.addWidget(self._info_browser, 0, Qt.AlignmentFlag.AlignTop)
        content_layout.addWidget(
            self._refs, 0, Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignRight
        )
        row_layout.addWidget(self._content, 1)

    def _sync_card_height(self, content_width: int) -> None:
        if self._refs.isVisible():
            self._refs.reflow_to_width(max(_THUMB_SIZE, content_width))
        refs_h = self._refs.sizeHint().height() if self._refs.isVisible() else 0
        browser_h = self._info_browser.height()
        content_h = browser_h + refs_h + 2
        self._content.setMinimumHeight(content_h)
        min_h = max(content_h, self._actions.sizeHint().height())
        self.setMinimumHeight(min_h)
        self.updateGeometry()

    def set_row_content(
        self,
        *,
        info_html: str,
        full_prompt: str,
        thumbnail_paths: list[str],
        content_width: int,
    ) -> None:
        self._full_prompt = full_prompt or ""
        install_delayed_prompt_tooltip(self._info_browser, self._full_prompt)
        self.update_info_html(info_html, content_width)
        self._replace_refs(thumbnail_paths, content_width)
        self._sync_card_height(content_width)

    def update_info_html(self, info_html: str, content_width: int) -> None:
        self._last_info_html = info_html or ""
        display_html = strip_references_from_status_html(self._last_info_html)
        _apply_task_info_html_to_browser(
            self._info_browser,
            display_html,
            content_width=max(80, content_width),
            job_queue_cell=True,
            max_height=None,
        )
        self._info_browser.setSizePolicy(
            QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed
        )

    def _replace_refs(self, paths: list[str], content_width: int) -> None:
        valid = _valid_preview_paths(paths)
        if (
            self._refs.isVisible()
            and getattr(self._refs, "_paths", None) == valid
        ):
            self._refs.reflow_to_width(max(_THUMB_SIZE, content_width))
            return
        layout = self._content.layout()
        if layout is None:
            return
        layout.removeWidget(self._refs)
        self._refs.deleteLater()
        self._refs = _FlowReferenceThumbs(self._main_window, paths)
        layout.addWidget(
            self._refs, 0, Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignRight
        )
        if self._refs._paths:
            self._refs.show()
            self._refs.reflow_to_width(max(_THUMB_SIZE, content_width))

    def reflow_refs(self, width: int) -> None:
        if self._refs.isVisible():
            self._refs.reflow_to_width(max(_THUMB_SIZE, width - _ACTION_COL_WIDTH - 20))
        self._sync_card_height(max(80, width - _ACTION_COL_WIDTH - 20))


class SidebarJobsWidget(QWidget):
    """Scrollable job queue for the right combined sidebar (dialog-equivalent data)."""

    def __init__(self, main_window, parent=None):
        super().__init__(parent)
        self.main_window = main_window
        self._controller = get_imagegen_controller(main_window)
        self._job_cards: list[_JobCard] = []
        self._refresh_table_timer: QTimer | None = None
        self._live_timer: QTimer | None = None
        self._resize_timer: QTimer | None = None
        self._signal_connected = False
        self._setup_ui()
        self._connect_controller()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._empty_label = QLabel("No jobs in the queue.")
        self._empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        t = get_active_theme()
        self._empty_label.setStyleSheet(
            f"color: {t.dialog_text_color_hex}; font-size: 12px; padding: 12px;"
        )

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.viewport().installEventFilter(self)

        self._list_host = QWidget()
        self._list_layout = QVBoxLayout(self._list_host)
        self._list_layout.setContentsMargins(4, 4, 4, 4)
        self._list_layout.setSpacing(8)
        self._list_layout.addStretch(1)

        self._scroll.setWidget(self._list_host)
        layout.addWidget(self._empty_label)
        layout.addWidget(self._scroll, 1)
        _disable_tab_focus(self)

    def _connect_controller(self) -> None:
        if self._signal_connected:
            return
        self._controller.queue_changed.connect(self._schedule_refresh_table)
        self._controller.task_status_info_changed.connect(
            lambda: self._refresh_active_row(force=True)
        )
        self._signal_connected = True
        timer = QTimer(self)
        timer.setInterval(500)
        timer.timeout.connect(lambda: self._refresh_active_row(force=False))
        timer.start()
        self._live_timer = timer

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._schedule_refresh_table()
        if self._live_timer is not None:
            self._live_timer.start()

    def hideEvent(self, event) -> None:
        if self._live_timer is not None:
            self._live_timer.stop()
        super().hideEvent(event)

    def eventFilter(self, obj, event) -> bool:
        if (
            hasattr(self, "_scroll")
            and obj is self._scroll.viewport()
            and event.type() == QEvent.Type.Resize
        ):
            self._schedule_reflow()
        return super().eventFilter(obj, event)

    def _schedule_reflow(self) -> None:
        timer = self._resize_timer
        if timer is None:
            timer = QTimer(self)
            timer.setSingleShot(True)
            timer.timeout.connect(self._reflow_all)
            self._resize_timer = timer
        timer.start(50)

    def _schedule_refresh_table(self) -> None:
        timer = self._refresh_table_timer
        if timer is None:
            timer = QTimer(self)
            timer.setSingleShot(True)
            timer.timeout.connect(self.refresh_table)
            self._refresh_table_timer = timer
        timer.start(0)

    def _viewport_width(self) -> int:
        w = self._scroll.viewport().width() if hasattr(self, "_scroll") else self.width()
        return max(120, w - 8)

    def _info_content_width(self) -> int:
        return max(80, self._viewport_width() - _ACTION_COL_WIDTH - 20)

    def _refresh_active_row(self, *, force: bool = False) -> None:
        if not self.isVisible() or not self._job_cards:
            return
        if not force and not self._controller.task_status_display_needs_refresh():
            return
        rows = self._controller.queue_snapshot()
        if not rows or not rows[0].is_active:
            return
        row = rows[0]
        info_html = info_html_for_queue_row(self._controller, 0, row)
        info_w = self._info_content_width()
        self._job_cards[0].update_info_html(info_html, info_w)
        self._job_cards[0]._replace_refs(row.thumbnail_paths, info_w)
        self._job_cards[0].reflow_refs(self._viewport_width())
        _disable_tab_focus(self._job_cards[0])

    def _clear_job_cards(self) -> None:
        while self._list_layout.count() > 1:
            item = self._list_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._job_cards.clear()

    def _reflow_all(self) -> None:
        width = self._viewport_width()
        info_w = self._info_content_width()
        for card in self._job_cards:
            if card._last_info_html:
                card.update_info_html(card._last_info_html, info_w)
            card.reflow_refs(width)

    def refresh_table(self) -> None:
        rows = self._controller.queue_snapshot()
        has_rows = bool(rows)
        self._empty_label.setVisible(not has_rows)
        self._scroll.setVisible(has_rows)
        self._clear_job_cards()

        info_w = self._info_content_width()
        for row_idx, row in enumerate(rows):
            info_html = info_html_for_queue_row(self._controller, row_idx, row)
            card = _JobCard(
                self.main_window,
                self._controller,
                row_idx,
                is_active=row.is_active,
            )
            card.set_row_content(
                info_html=info_html,
                full_prompt=row.full_prompt,
                thumbnail_paths=row.thumbnail_paths,
                content_width=info_w,
            )
            self._list_layout.insertWidget(self._list_layout.count() - 1, card)
            self._job_cards.append(card)
            _disable_tab_focus(card)

        self._schedule_reflow()
        _disable_tab_focus(self)
