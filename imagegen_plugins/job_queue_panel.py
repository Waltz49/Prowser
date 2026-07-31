#!/usr/bin/env python3
"""Shared job queue list UI (job cards, progress strip) for pane and dialog."""

from __future__ import annotations

import os
from typing import Callable

from PySide6.QtCore import QEvent, QEventLoop, Qt, QTimer, QSize, QPoint, QObject, QMimeData
from PySide6.QtGui import QColor, QDrag, QIcon, QMouseEvent, QPainter, QPen
from PySide6.QtWidgets import (
    QApplication,
    QAbstractButton,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from imagegen_plugins.active_job_strip_widget import ActiveJobStripWidget
from imagegen_plugins.image_gen_controller import get_imagegen_controller
from imagegen_plugins.job_queue_common import (
    _ACTION_BAR_HEIGHT,
    _apply_job_queue_cell_background,
    _valid_preview_paths,
    JobQueueActionBar,
    create_invalid_job_preview_label,
    info_html_for_queue_row,
    job_queue_edit_row,
    open_reference_thumbnail_paths,
)
from config import job_queue_cell_background_hex
from imagegen_plugins.job_prompt_tooltip import (
    install_delayed_prompt_tooltip,
    update_delayed_prompt_tooltip,
)
from status_bar_config import (
    _apply_task_info_html_to_browser,
    configure_task_info_text_browser,
)
from theme.theme_service import get_active_theme
from browser_window.sidebar.sidebar_pane_chrome import apply_scroll_area_viewport_background
from thumbnails.sidebar_pane_layout import MIN_JOBS_QUEUE_CONTENT_HEIGHT, pane_fit_height_tolerance
from thumbnails import thumbnail_constants as tc
from utils import create_job_status_thumbnail_label

_JOB_QUEUE_DRAG_MIME = "application/x-prowser-job-queue-id"
_CARD_CONTENT_MARGIN = 12
_DROP_LINE_HEIGHT = 6
_DROP_LINE_COLOR = QColor(40, 120, 250, 220)
_DROP_LINE_PEN_WIDTH = 1

_THUMB_SIZE = 55
_THUMB_GAP = 14

# Sidebar Job Control pane minimum content width (px).
MIN_JOBS_PANE_WIDTH = 250

# Floating Job Control dialog minimum content width (px). Outer min = + 2× margin.
MIN_JOB_WIN_WIDTH = 210 # DGN hardcoded to current font sizes

QUEUE_SIZE_ALL = "all"
QUEUE_SIZE_ONE = "one"
QUEUE_SIZE_STRIP = "strip"
_QUEUE_SIZE_MODES = (QUEUE_SIZE_ALL, QUEUE_SIZE_ONE, QUEUE_SIZE_STRIP)

_EMPTY_LABEL_FONT_PX = 12
_EMPTY_LABEL_HEIGHT_LINES = 1.5


def _empty_queue_label_stylesheet(text_hex: str) -> str:
    return (
        f"color: {text_hex}; font-size: {_EMPTY_LABEL_FONT_PX}px; "
        "padding: 0px 8px; margin: 0px;"
    )


def empty_queue_label_height_px(label: QLabel) -> int:
    """~1.5 line heights for the empty-queue message."""
    fm = label.fontMetrics()
    return int(fm.height() * _EMPTY_LABEL_HEIGHT_LINES)


def _apply_empty_queue_label_style(label: QLabel, text_hex: str) -> None:
    label.setStyleSheet(_empty_queue_label_stylesheet(text_hex))
    h = empty_queue_label_height_px(label)
    label.setFixedHeight(h)


def job_control_dialog_outer_minimum_width(*, margin_px: int = 0) -> int:
    """Minimum outer width for the floating job control dialog."""
    return MIN_JOB_WIN_WIDTH + 2 * margin_px

# When scroll viewport width exceeds this and a row has 1–2 reference images, show
# them in a vertical column beside the text instead of below it.
JOB_CELL_INLINE_REFS_MIN_SCROLL_WIDTH = 350
JOB_CELL_INLINE_REFS_RIGHT_PADDING_PX = 2
_JOB_CELL_INLINE_TEXT_REFS_SPACING = 4


def jobs_header_status_text(controller) -> str:
    """Title-bar queue summary: waiting jobs only."""
    waiting = sum(1 for row in controller.queue_snapshot() if not row.is_active)
    if waiting > 0:
        return f"+{waiting} "
    return ""


def show_jobs_tools_menu(
    main_window,
    controller,
    anchor: QPushButton,
    *,
    job_queue_dialog=None,
) -> None:
    menu = QMenu(anchor)
    t = get_active_theme()
    menu.setStyleSheet(t.status_bar_context_menu_stylesheet())

    inter_action = menu.addAction("Intermediate Images")
    inter_action.setCheckable(True)
    prog_state = controller.get_show_progressive_images_menu_state()
    if prog_state is None:
        inter_action.setEnabled(False)
        inter_action.setChecked(False)
    else:
        _supported, enabled = prog_state
        inter_action.setChecked(bool(enabled))
        inter_action.triggered.connect(
            lambda checked: controller.set_show_progressive_images(bool(checked))
        )

    hold_action = menu.addAction("Hold Job Queue")
    hold_action.setCheckable(True)
    hold_action.setChecked(controller.hold_job_queue())
    hold_action.triggered.connect(
        lambda checked: controller.set_hold_job_queue(bool(checked))
    )

    if job_queue_dialog is not None and hasattr(
        job_queue_dialog, "is_job_queue_always_on_top"
    ):
        menu.addSeparator()
        top_action = menu.addAction("Always on Top")
        top_action.setCheckable(True)
        top_action.setChecked(job_queue_dialog.is_job_queue_always_on_top())
        top_action.triggered.connect(
            lambda checked: job_queue_dialog.set_job_queue_always_on_top(bool(checked))
        )

    skip_copy_action = menu.addAction("Skip This Copy")
    skip_copy_action.setEnabled(controller.can_skip_active_series_copy())
    skip_copy_action.setToolTip(
        "End the current copy and start the next one in this series."
    )
    skip_copy_action.triggered.connect(controller.skip_active_series_copy)

    menu.exec(anchor.mapToGlobal(QPoint(0, anchor.height())))


def _disable_tab_focus(root: QWidget) -> None:
    """Keep job pane controls out of the keyboard tab order."""
    root.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    for child in root.findChildren(QWidget):
        child.setFocusPolicy(Qt.FocusPolicy.NoFocus)


def _job_selection_border_hex() -> str:
    """Active thumbnail index highlight (Settings → current image border)."""
    hex_val = (tc.CURRENT_IMAGE_BORDER_COLOR_HEX or "").strip()
    if hex_val:
        return hex_val
    return get_active_theme().current_image_border_color_hex


def _job_selection_border_width_px() -> int:
    w = int(tc.CURRENT_IMAGE_BORDER_WIDTH_PX or 0)
    if w > 0:
        return w
    t = get_active_theme()
    idx = int(getattr(t, "current_image_border_width_index", 2))
    return max(1, min(10, idx))


def _job_card_stylesheet(*, selected: bool = False) -> str:
    t = get_active_theme()
    bg = job_queue_cell_background_hex()
    if selected:
        border = _job_selection_border_hex()
        width = _job_selection_border_width_px()
    else:
        border = t.border_default_hex
        width = 1
    return f"""
        QFrame#sidebarJobCard {{
            background-color: {bg};
            color: {t.sidebar_text_color_hex};
            border: {width}px solid {border};
            border-radius: 4px;
            padding: 0px;
            margin: 0px;
        }}
    """


def refresh_jobs_flyout_buttons(main_window) -> None:
    from imagegen_plugins.jobs_display_mode import (
        JOBS_DISPLAY_PANE,
        get_jobs_display_mode,
    )

    from theme.titlebar_icons import (
        apply_titlebar_button_icons,
        titlebar_flyout_icon_pair,
    )

    pane_mode = get_jobs_display_mode(main_window) == JOBS_DISPLAY_PANE
    tooltip = (
        "Open job queue in floating panel"
        if pane_mode
        else "Dock job queue in sidebar pane"
    )
    panels = []
    rs = getattr(main_window, "right_sidebar", None)
    if rs is not None:
        w = getattr(rs, "jobs_widget", None)
        if w is not None:
            panels.append(w)
    dlg = getattr(main_window, "_imagegen_job_queue_dialog", None)
    if dlg is not None and getattr(dlg, "_panel", None) is not None:
        panels.append(dlg._panel)
    for panel in panels:
        btn = getattr(panel, "_flyout_button", None)
        if btn is None:
            continue
        btn.setProperty("_titlebar_flyout_pane_mode", pane_mode)
        btn.setToolTip(tooltip)
        apply_titlebar_button_icons(btn, *titlebar_flyout_icon_pair(pane_mode))


class _JobQueueDropLine(QWidget):
    """Horizontal insertion marker (matches thumbnail canvas drop indicator style)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAutoFillBackground(False)
        self.hide()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(QPen(_DROP_LINE_COLOR, _DROP_LINE_PEN_WIDTH))
        mid_y = self.height() // 2
        painter.drawLine(0, mid_y, self.width(), mid_y)


class _FlowReferenceThumbs(QWidget):
    """Reference thumbnails in right-aligned rows; wrap on resize."""

    def __init__(
        self,
        main_window,
        paths: list[str],
        *,
        references_invalid: bool = False,
        parent=None,
    ):
        super().__init__(parent)
        self._main_window = main_window
        self._references_invalid = bool(references_invalid)
        self._paths = [] if self._references_invalid else _valid_preview_paths(paths)
        self._cells: list[QLabel] = []
        self._last_cols: int | None = None
        self._last_reflow_width = 0
        self._reflow_guard = False
        if self._references_invalid:
            self.setCursor(Qt.CursorShape.ArrowCursor)
        else:
            self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAttribute(Qt.WidgetAttribute.WA_DontCreateNativeAncestors, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NativeWindow, False)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._outer = QVBoxLayout(self)
        self._outer.setContentsMargins(0, 2, 0, 0)
        self._outer.setSpacing(_THUMB_GAP)
        if self._references_invalid:
            thumb = create_invalid_job_preview_label(_THUMB_SIZE)
            thumb.setToolTip("Reference files for this job are missing")
            self._cells.append(thumb)
            self.reflow_to_width(_THUMB_SIZE)
            return
        for path in self._paths:
            thumb = create_job_status_thumbnail_label(path, _THUMB_SIZE)
            thumb.setCursor(Qt.CursorShape.PointingHandCursor)
            thumb.setAttribute(Qt.WidgetAttribute.WA_DontCreateNativeAncestors, True)
            thumb.setAttribute(Qt.WidgetAttribute.WA_NativeWindow, False)
            thumb.setToolTip(os.path.basename(path))
            self._cells.append(thumb)
        if self._paths:
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

    def reflow_to_width(self, width: int, *, force_cols: int | None = None) -> None:
        width = self._effective_reflow_width(width)
        self._last_reflow_width = width
        if self._reflow_guard or not self._cells:
            return
        cols = force_cols if force_cols is not None else self._cols_for_width(width)
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
        if (
            event.button() == Qt.MouseButton.LeftButton
            and self._paths
            and not self._references_invalid
        ):
            open_reference_thumbnail_paths(self._main_window, self._paths)
            event.accept()
            return
        super().mousePressEvent(event)


class _JobCardDblClickFilter(QObject):
    """Open the job editor on double-click (viewport + browser)."""

    def __init__(self, opener: Callable[[], None], parent: QObject | None = None):
        super().__init__(parent)
        self._opener = opener

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        if event.type() == QEvent.Type.MouseButtonDblClick:
            mouse_event = event  # type: ignore[assignment]
            if mouse_event.button() == Qt.MouseButton.LeftButton:
                self._opener()
                return True
        return False


class JobCard(QFrame):
    """One queue row: status HTML + thumbnails (actions live in shared bar)."""

    def __init__(
        self,
        main_window,
        controller,
        row_idx: int,
        *,
        job_id: str,
        is_active: bool,
        on_select: Callable[[str], None] | None = None,
        on_reorder_drop: Callable[[str, int], None] | None = None,
        on_drop_hover: Callable[[int], None] | None = None,
        on_drop_hover_clear: Callable[[], None] | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self.setObjectName("sidebarJobCard")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setAcceptDrops(True)
        self._main_window = main_window
        self._controller = controller
        self._row_idx = row_idx
        self._job_id = job_id
        self._is_active = bool(is_active)
        self._on_select = on_select
        self._on_reorder_drop = on_reorder_drop
        self._on_drop_hover = on_drop_hover
        self._on_drop_hover_clear = on_drop_hover_clear
        self._selected = False
        self._full_prompt = ""
        self._last_info_html = ""
        self._scroll_width = 0
        self._content_inline = False
        self._last_content_width = 0
        self._drag_start_pos: QPoint | None = None
        self._drag_started = False
        self._apply_card_style()

        row_layout = QHBoxLayout(self)
        row_layout.setContentsMargins(2, 2, 2, 2)
        row_layout.setSpacing(4)

        self._content = QWidget()
        _apply_job_queue_cell_background(self._content)

        self._info_browser = QTextBrowser()
        self._dblclick_filter: _JobCardDblClickFilter | None = None
        configure_task_info_text_browser(
            self._info_browser, main_window, job_queue_cell=True
        )
        self._info_browser.setSizePolicy(
            QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed
        )
        self._info_browser.viewport().installEventFilter(self)

        self._refs = _FlowReferenceThumbs(main_window, [])
        self._ensure_content_layout(False)
        row_layout.addWidget(self._content, 1)

    def job_id(self) -> str:
        return self._job_id

    def row_index(self) -> int:
        return self._row_idx

    def set_row_index(self, row_idx: int) -> None:
        self._row_idx = row_idx

    def is_active_row(self) -> bool:
        return self._is_active

    def set_selected(self, selected: bool) -> None:
        selected = bool(selected)
        if self._selected == selected:
            return
        self._selected = selected
        self._apply_card_style()
        if self._last_content_width > 0:
            self._sync_card_height(
                self._last_content_width,
                scroll_width=self._scroll_width or None,
            )
        else:
            self.updateGeometry()

    def _frame_border_width_px(self) -> int:
        return _job_selection_border_width_px() if self._selected else 1

    def _layout_vertical_margins_px(self) -> int:
        layout = self.layout()
        if layout is None:
            return 4
        m = layout.contentsMargins()
        return m.top() + m.bottom()

    def _card_frame_minimum_height(self, content_h: int) -> int:
        return content_h + self._layout_vertical_margins_px() + (
            2 * self._frame_border_width_px()
        )

    def _apply_card_style(self) -> None:
        self.setStyleSheet(_job_card_stylesheet(selected=self._selected))
        if not self._is_active:
            self.setCursor(
                Qt.CursorShape.OpenHandCursor
                if not self._drag_started
                else Qt.CursorShape.ClosedHandCursor
            )
        else:
            self.setCursor(Qt.CursorShape.ArrowCursor)

    def _select_self(self) -> None:
        if self._on_select is not None:
            self._on_select(self._job_id)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._select_self()
            if not self._is_active:
                self._drag_start_pos = event.position().toPoint()
                self._drag_started = False
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if (
            not self._is_active
            and self._drag_start_pos is not None
            and event.buttons() & Qt.MouseButton.LeftButton
            and not self._drag_started
        ):
            distance = (event.position().toPoint() - self._drag_start_pos).manhattanLength()
            if distance >= QApplication.startDragDistance():
                self._start_drag()
                self._drag_started = True
                event.accept()
                return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self._drag_start_pos = None
        self._drag_started = False
        if not self._is_active:
            self.setCursor(Qt.CursorShape.OpenHandCursor)
        super().mouseReleaseEvent(event)

    def _start_drag(self) -> None:
        mime = QMimeData()
        mime.setData(_JOB_QUEUE_DRAG_MIME, self._job_id.encode("utf-8"))
        drag = QDrag(self)
        drag.setMimeData(mime)
        try:
            drag.exec(Qt.DropAction.MoveAction)
        finally:
            if self._on_drop_hover_clear is not None:
                self._on_drop_hover_clear()

    def _reorder_drag_payload(self, event) -> str | None:
        if not event.mimeData().hasFormat(_JOB_QUEUE_DRAG_MIME):
            return None
        payload = bytes(event.mimeData().data(_JOB_QUEUE_DRAG_MIME)).decode("utf-8")
        if not payload or payload == self._job_id:
            return None
        return payload

    def _insert_index_for_drag_y(self, local_y: float) -> int:
        insert_after = local_y > (self.height() / 2)
        return self._row_idx + (1 if insert_after else 0)

    def dragEnterEvent(self, event) -> None:
        if self._reorder_drag_payload(event) is not None:
            if self._on_drop_hover is not None:
                self._on_drop_hover(self._insert_index_for_drag_y(event.position().y()))
            event.acceptProposedAction()
            return
        event.ignore()

    def dragMoveEvent(self, event) -> None:
        if self._reorder_drag_payload(event) is not None:
            if self._on_drop_hover is not None:
                self._on_drop_hover(self._insert_index_for_drag_y(event.position().y()))
            event.acceptProposedAction()
            return
        event.ignore()

    def dropEvent(self, event) -> None:
        payload = self._reorder_drag_payload(event)
        if payload is None:
            event.ignore()
            return
        target_row = self._insert_index_for_drag_y(event.position().y())
        if self._on_reorder_drop is not None:
            self._on_reorder_drop(payload, target_row)
        event.acceptProposedAction()

    def eventFilter(self, obj, event) -> bool:
        if obj is self._info_browser.viewport():
            if event.type() == QEvent.Type.MouseButtonPress:
                mouse = event  # type: ignore[assignment]
                if mouse.button() == Qt.MouseButton.LeftButton:
                    local = mouse.position().toPoint()
                    if not self._info_browser.anchorAt(local):
                        self._select_self()
                        if not self._is_active:
                            self._drag_start_pos = mouse.position().toPoint()
                            self._drag_started = False
                        return True
            if event.type() == QEvent.Type.MouseMove and not self._is_active:
                mouse = event  # type: ignore[assignment]
                if (
                    self._drag_start_pos is not None
                    and mouse.buttons() & Qt.MouseButton.LeftButton
                    and not self._drag_started
                ):
                    distance = (
                        mouse.position().toPoint() - self._drag_start_pos
                    ).manhattanLength()
                    if distance >= QApplication.startDragDistance():
                        self._start_drag()
                        self._drag_started = True
                        return True
            if event.type() == QEvent.Type.MouseButtonRelease:
                self._drag_start_pos = None
                self._drag_started = False
        return super().eventFilter(obj, event)

    def _ensure_dblclick_edit_filter(self) -> None:
        """Install after prompt tooltip so this filter runs first on dbl-click."""
        if self._dblclick_filter is not None:
            return
        opener = lambda: job_queue_edit_row(
            self._main_window, self._controller, self._row_idx
        )
        filt = _JobCardDblClickFilter(opener, parent=self)
        self._dblclick_filter = filt
        self._info_browser.installEventFilter(filt)
        viewport = self._info_browser.viewport()
        if viewport is not None:
            viewport.installEventFilter(filt)

    def _ref_count(self) -> int:
        if getattr(self._refs, "_references_invalid", False):
            return 1
        return len(getattr(self._refs, "_paths", []) or [])

    def _use_inline_refs_layout(self, scroll_width: int) -> bool:
        return (
            scroll_width > JOB_CELL_INLINE_REFS_MIN_SCROLL_WIDTH
            and 1 <= self._ref_count() <= 2
        )

    def _browser_content_width(self, content_width: int, scroll_width: int) -> int:
        if self._use_inline_refs_layout(scroll_width):
            reserved = (
                _THUMB_SIZE
                + JOB_CELL_INLINE_REFS_RIGHT_PADDING_PX
                + _JOB_CELL_INLINE_TEXT_REFS_SPACING
            )
            return max(80, content_width - reserved)
        return max(80, content_width)

    def _ensure_content_layout(self, inline: bool) -> None:
        if inline == self._content_inline and self._content.layout() is not None:
            return
        self._content_inline = inline
        old_layout = self._content.layout()
        if old_layout is not None:
            old_layout.removeWidget(self._info_browser)
            old_layout.removeWidget(self._refs)
            QWidget().setLayout(old_layout)
        if inline:
            layout = QHBoxLayout(self._content)
            layout.setContentsMargins(
                0, 0, JOB_CELL_INLINE_REFS_RIGHT_PADDING_PX, 0
            )
            layout.setSpacing(_JOB_CELL_INLINE_TEXT_REFS_SPACING)
            self._refs.setSizePolicy(
                QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed
            )
            layout.addWidget(self._info_browser, 1, Qt.AlignmentFlag.AlignTop)
            layout.addWidget(
                self._refs,
                0,
                Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignRight,
            )
        else:
            layout = QVBoxLayout(self._content)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(2)
            self._refs.setSizePolicy(
                QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
            )
            layout.addWidget(self._info_browser, 0, Qt.AlignmentFlag.AlignTop)
            layout.addWidget(
                self._refs,
                0,
                Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignRight,
            )

    def _reflow_visible_refs(self, content_width: int, scroll_width: int) -> None:
        if not self._refs.isVisible():
            return
        if self._use_inline_refs_layout(scroll_width):
            self._refs.reflow_to_width(_THUMB_SIZE, force_cols=1)
        else:
            self._refs.reflow_to_width(max(_THUMB_SIZE, content_width))

    def _sync_card_height(
        self,
        content_width: int,
        *,
        browser_h: int | None = None,
        scroll_width: int | None = None,
    ) -> None:
        sw = scroll_width if scroll_width is not None else self._scroll_width
        self._ensure_content_layout(self._use_inline_refs_layout(sw))
        self._reflow_visible_refs(content_width, sw)
        refs_h = self._refs.sizeHint().height() if self._refs.isVisible() else 0
        if browser_h is None:
            browser_h = self._info_browser.height()
        if self._use_inline_refs_layout(sw):
            content_h = max(browser_h, refs_h) + 2
        else:
            content_h = browser_h + refs_h + 2
        self._content.setMinimumHeight(content_h)
        self._content.setMaximumHeight(content_h)
        frame_h = self._card_frame_minimum_height(content_h)
        self.setMinimumHeight(frame_h)
        self.setMaximumHeight(16777215)
        self.updateGeometry()

    def set_row_content(
        self,
        *,
        info_html: str,
        full_prompt: str,
        thumbnail_paths: list[str],
        content_width: int,
        scroll_width: int,
        references_invalid: bool = False,
    ) -> None:
        self._scroll_width = scroll_width
        self._full_prompt = full_prompt or ""
        install_delayed_prompt_tooltip(self._info_browser, self._full_prompt)
        self._ensure_dblclick_edit_filter()
        self._replace_refs(
            thumbnail_paths,
            content_width,
            scroll_width=scroll_width,
            references_invalid=references_invalid,
        )
        self.update_info_html(info_html, content_width, scroll_width=scroll_width)

    def update_info_html(
        self,
        info_html: str,
        content_width: int,
        *,
        scroll_width: int | None = None,
    ) -> None:
        sw = (
            scroll_width
            if scroll_width is not None
            else self._scroll_width or (content_width + _CARD_CONTENT_MARGIN)
        )
        self._scroll_width = sw
        self._last_content_width = content_width
        self._ensure_content_layout(self._use_inline_refs_layout(sw))
        self._last_info_html = info_html or ""
        text_w = self._browser_content_width(content_width, sw)
        browser_h = _apply_task_info_html_to_browser(
            self._info_browser,
            self._last_info_html,
            content_width=text_w,
            job_queue_cell=True,
            max_height=None,
        )
        self._info_browser.setSizePolicy(
            QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed
        )
        self._sync_card_height(content_width, browser_h=browser_h, scroll_width=sw)

    def _replace_refs(
        self,
        paths: list[str],
        content_width: int,
        *,
        scroll_width: int | None = None,
        references_invalid: bool = False,
    ) -> None:
        sw = (
            scroll_width
            if scroll_width is not None
            else self._scroll_width or (content_width + _CARD_CONTENT_MARGIN)
        )
        self._scroll_width = sw
        valid = [] if references_invalid else _valid_preview_paths(paths)
        inline = self._use_inline_refs_layout(sw)
        if (
            self._refs.isVisible()
            and getattr(self._refs, "_paths", None) == valid
            and getattr(self._refs, "_references_invalid", False) == references_invalid
            and inline == self._content_inline
        ):
            self._reflow_visible_refs(content_width, sw)
            return
        layout = self._content.layout()
        if layout is not None:
            layout.removeWidget(self._refs)
        self._refs.deleteLater()
        self._refs = _FlowReferenceThumbs(
            self._main_window,
            paths,
            references_invalid=references_invalid,
        )
        mode_changed = inline != self._content_inline
        self._ensure_content_layout(inline)
        if not mode_changed:
            layout = self._content.layout()
            if layout is not None:
                layout.addWidget(
                    self._refs,
                    0,
                    Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignRight,
                )
        self._reflow_visible_refs(content_width, sw)

    def reflow_refs(self, scroll_width: int) -> None:
        content_width = max(80, scroll_width - _CARD_CONTENT_MARGIN)
        self._scroll_width = scroll_width
        self._ensure_content_layout(self._use_inline_refs_layout(scroll_width))
        if self._last_info_html:
            self.update_info_html(
                self._last_info_html, content_width, scroll_width=scroll_width
            )
        else:
            self._reflow_visible_refs(content_width, scroll_width)
            self._sync_card_height(content_width, scroll_width=scroll_width)


class JobQueuePanelWidget(QWidget):
    """Scrollable job queue with active progress strip (shared by pane and dialog)."""

    def __init__(self, main_window, parent=None, *, job_control_dialog: bool = False):
        super().__init__(parent)
        self.main_window = main_window
        self._job_control_dialog = job_control_dialog
        self._controller = get_imagegen_controller(main_window)
        self._job_cards: list[JobCard] = []
        self._refresh_table_timer: QTimer | None = None
        self._live_timer: QTimer | None = None
        self._resize_timer: QTimer | None = None
        self._queue_size_mode = QUEUE_SIZE_ALL
        self._signal_connected = False
        self._live_refresh_paused = False
        self._header_getter: Callable[[], QWidget | None] | None = None
        self._on_compact_geometry_changed: Callable[[], None] | None = None
        self._floating_window: QWidget | None = None
        self._floating_drag_via_client_getter: Callable[[], bool] | None = None
        self._floating_double_click_callback: Callable[[], None] | None = None
        self._floating_drag_filter_targets: list[QWidget] = []
        self._preparing_size_measure = False
        self._flyout_button: QPushButton | None = None
        self._drop_indicator_index: int | None = None
        self._drop_line: _JobQueueDropLine | None = None
        self._setup_ui()
        self._connect_controller()

    def set_header_getter(self, getter: Callable[[], QWidget | None] | None) -> None:
        self._header_getter = getter

    def set_on_compact_geometry_changed(
        self, callback: Callable[[], None] | None
    ) -> None:
        self._on_compact_geometry_changed = callback

    def configure_floating_window_move(
        self,
        window: QWidget | None,
        *,
        drag_via_client_getter: Callable[[], bool] | None = None,
        double_click_callback: Callable[[], None] | None = None,
    ) -> None:
        """Drag the frameless dialog from client chrome when the title bar is hidden."""
        self._floating_window = window
        self._floating_drag_via_client_getter = drag_via_client_getter
        self._floating_double_click_callback = double_click_callback
        for widget in self._floating_drag_filter_targets:
            widget.removeEventFilter(self)
        self._floating_drag_filter_targets.clear()
        if window is None:
            return
        targets = [self._active_job_strip, self._empty_label]
        strip = self._active_job_strip
        for attr in ("_frame", "_browser"):
            child = getattr(strip, attr, None)
            if child is not None:
                targets.append(child)
        browser = getattr(strip, "_browser", None)
        if browser is not None and browser.viewport() is not None:
            targets.append(browser.viewport())
        for widget in targets:
            widget.installEventFilter(self)
            self._floating_drag_filter_targets.append(widget)

    def _floating_client_drag_active(self) -> bool:
        return (
            self._floating_window is not None
            and self._floating_drag_via_client_getter is not None
            and self._floating_drag_via_client_getter()
        )

    def _mouse_event_hits_interactive_target(
        self, event: QMouseEvent, watched: QObject
    ) -> bool:
        widget = watched if isinstance(watched, QWidget) else None
        while widget is not None:
            if isinstance(widget, QAbstractButton):
                return True
            if isinstance(widget, QTextBrowser):
                vp = widget.viewport()
                if vp is not None:
                    local = vp.mapFromGlobal(event.globalPosition().toPoint())
                    if widget.anchorAt(local):
                        return True
                return False
            widget = widget.parentWidget()
        return False

    def _try_start_floating_client_drag(
        self, event: QMouseEvent, watched: QObject | None = None
    ) -> bool:
        if not self._floating_client_drag_active():
            return False
        if event.button() != Qt.MouseButton.LeftButton:
            return False
        if watched is not None and self._mouse_event_hits_interactive_target(
            event, watched
        ):
            return False
        from utils import try_start_frameless_system_move

        if try_start_frameless_system_move(
            self._floating_window, event.globalPosition().toPoint()
        ):
            event.accept()
            return True
        return False

    def _try_handle_floating_client_double_click(
        self, event: QMouseEvent, watched: QObject | None = None
    ) -> bool:
        if not self._floating_client_drag_active():
            return False
        if event.button() != Qt.MouseButton.LeftButton:
            return False
        if watched is not None and self._mouse_event_hits_interactive_target(
            event, watched
        ):
            return False
        cb = self._floating_double_click_callback
        if cb is None:
            return False
        cb()
        event.accept()
        return True

    def attach_header_tools(self) -> None:
        """Wire titlebar tools menu and flyout button on the bound header (if any)."""
        header = self._jobs_header()
        if header is None:
            return
        btn = QPushButton()
        btn.setToolTip("Job queue tools")
        btn.clicked.connect(
            lambda: show_jobs_tools_menu(
                self.main_window,
                self._controller,
                btn,
                job_queue_dialog=(
                    self.window()
                    if hasattr(self.window(), "is_job_queue_always_on_top")
                    else None
                ),
            )
        )
        if hasattr(header, "set_tools_button"):
            header.set_tools_button(btn)

        fly_btn = QPushButton()
        fly_btn.clicked.connect(self._on_flyout_clicked)
        if hasattr(header, "set_flyout_button"):
            header.set_flyout_button(fly_btn)
        self._flyout_button = fly_btn
        refresh_jobs_flyout_buttons(self.main_window)

    def _on_flyout_clicked(self) -> None:
        sm = getattr(self.main_window, "sidebar_manager", None)
        if sm is not None and hasattr(sm, "toggle_jobs_display_mode"):
            sm.toggle_jobs_display_mode()
            return
        from imagegen_plugins.jobs_display_mode import toggle_jobs_display_mode

        toggle_jobs_display_mode(self.main_window)

    def _on_job_selected(self, job_id: str) -> None:
        self._controller.set_selected_job_id(job_id)
        self._sync_all_panels_selection()

    def _sync_all_panels_selection(self) -> None:
        self._sync_selection_ui()
        mw = self.main_window
        rs = getattr(mw, "right_sidebar", None)
        other = getattr(rs, "jobs_widget", None) if rs is not None else None
        if other is not None and other is not self:
            other._sync_selection_ui()
        dlg = getattr(mw, "_imagegen_job_queue_dialog", None)
        panel = getattr(dlg, "_panel", None) if dlg is not None else None
        if panel is not None and panel is not self:
            panel._sync_selection_ui()

    def _should_show_action_bar(self) -> bool:
        """Show unless strip-only progress view or no jobs in queue."""
        if self._queue_size_mode == QUEUE_SIZE_STRIP:
            return False
        return bool(self._job_cards) or self._controller.is_running()

    def _action_bar_block_height(self) -> int:
        if not self._should_show_action_bar():
            return 0
        h = self._action_bar.height()
        if h > 0:
            return h
        hint = self._action_bar.sizeHint().height()
        return hint if hint > 0 else _ACTION_BAR_HEIGHT

    def _card_layout_height(self, card: JobCard) -> int:
        h = card.minimumHeight()
        if h > 0:
            return h
        return card.sizeHint().height()

    def _on_job_reorder_drop(self, job_id: str, target_display_row: int) -> None:
        self._clear_drop_indicator()
        self._controller.move_job_to_display_row(job_id, target_display_row)

    def _insert_index_at_list_y(self, y: int) -> int:
        for idx, card in enumerate(self._job_cards):
            if y < card.geometry().center().y():
                return idx
        return len(self._job_cards)

    def _drop_line_geometry(self, insert_index: int) -> tuple[int, int, int]:
        margins = self._list_layout.contentsMargins()
        spacing = self._list_layout.spacing()
        viewport = self._scroll.viewport()
        if not self._job_cards:
            x_host = margins.left()
            w = max(1, self._list_host.width() - margins.left() - margins.right())
            y_host = margins.top()
            pt = self._list_host.mapTo(viewport, QPoint(x_host, y_host))
            return pt.x(), pt.y(), w

        if insert_index <= 0:
            ref = self._job_cards[0]
            if ref.is_active_row() and len(self._job_cards) > 1:
                ref = self._job_cards[1]
            gap_host = ref.mapTo(self._list_host, QPoint(0, 0))
            gap_y = gap_host.y() - max(1, spacing // 2)
        elif insert_index >= len(self._job_cards):
            ref = self._job_cards[-1]
            gap_host = ref.mapTo(self._list_host, QPoint(0, ref.height()))
            gap_y = gap_host.y() + max(1, spacing // 2)
        else:
            ref = self._job_cards[insert_index]
            gap_host = ref.mapTo(self._list_host, QPoint(0, 0))
            gap_y = gap_host.y() - max(1, spacing // 2)

        ref_tl = ref.mapTo(self._list_host, QPoint(0, 0))
        pt = self._list_host.mapTo(viewport, QPoint(ref_tl.x(), gap_y))
        return pt.x(), pt.y(), ref.width()

    def _show_drop_indicator(self, insert_index: int) -> None:
        insert_index = max(0, min(int(insert_index), len(self._job_cards)))
        self._drop_indicator_index = insert_index
        line = self._drop_line
        if line is None:
            return
        x, y, w = self._drop_line_geometry(insert_index)
        line.setGeometry(
            x, y - _DROP_LINE_HEIGHT // 2, max(1, w), _DROP_LINE_HEIGHT
        )
        line.show()
        line.raise_()
        line.update()

    def _clear_drop_indicator(self) -> None:
        self._drop_indicator_index = None
        if self._drop_line is not None:
            self._drop_line.hide()

    def _on_job_list_scrolled(self, _value: int) -> None:
        if self._drop_indicator_index is not None:
            self._show_drop_indicator(self._drop_indicator_index)

    def _sync_selection_ui(self) -> None:
        selected_id = self._controller.selected_job_id()
        row_idx = self._controller.resolve_selected_row_index()
        for card in self._job_cards:
            card.set_selected(card.job_id() == selected_id)
        if self._should_show_action_bar():
            self._action_bar.show()
            self._action_bar.update_for_row(row_idx)
        else:
            self._action_bar.hide()
        self._reflow_all()
        self._notify_shell_geometry_changed()

    def schedule_refresh(self) -> None:
        """Defer table rebuild (safe during controller signal handlers)."""
        self._schedule_refresh_table()

    def has_job_rows(self) -> bool:
        return bool(self._job_cards)

    def has_active_generation(self) -> bool:
        return self._controller.is_running()

    def should_shrink_wrap_client(self) -> bool:
        """True when client area should hug content (empty queue, no active strip)."""
        return not self._job_cards and not self._controller.is_running()

    def is_queue_list_visible(self) -> bool:
        return self._scroll.isVisible()

    def empty_label_widget(self) -> QLabel:
        return self._empty_label

    def empty_state_height_hint(self) -> int:
        return empty_queue_label_height_px(self._empty_label)

    def prepare_expand_layout(self) -> None:
        """Reflow cards and progress strip before sizing to fit content."""
        self._reflow_all()
        self._refresh_active_job_strip(force=True)

    def _jobs_header(self):
        if self._header_getter is None:
            return None
        return self._header_getter()

    def _setup_ui(self) -> None:
        self.setMinimumWidth(0)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._empty_label = QLabel("No jobs in the queue.")
        self._empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        t = get_active_theme()
        _apply_empty_queue_label_style(
            self._empty_label, t.sidebar_text_color_hex
        )

        self._active_job_strip = ActiveJobStripWidget(self.main_window, self)
        self._active_job_strip.set_on_content_height_changed(
            self._on_active_strip_content_height_changed
        )

        self._action_bar = JobQueueActionBar(
            self.main_window, self._controller, self
        )
        self._action_bar.hide()

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self._scroll.setMinimumHeight(0)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setStyleSheet(get_active_theme().sidebar_jobs_scroll_stylesheet())
        apply_scroll_area_viewport_background(self._scroll, t.sidebar_background_color_hex)
        vp = self._scroll.viewport()
        if vp:
            vp.installEventFilter(self)

        self._list_host = QWidget()
        self._list_host.setAcceptDrops(True)
        self._list_host.installEventFilter(self)
        self._list_layout = QVBoxLayout(self._list_host)
        self._list_layout.setContentsMargins(4, 4, 4, 4)
        self._list_layout.setSpacing(8)
        self._list_layout.addStretch(1)

        self._drop_line = _JobQueueDropLine(self._scroll.viewport())

        self._scroll.setWidget(self._list_host)
        self._scroll.verticalScrollBar().valueChanged.connect(
            self._on_job_list_scrolled
        )
        self._panel_layout = layout
        layout.addWidget(self._active_job_strip)
        layout.addWidget(self._action_bar)
        layout.addWidget(self._empty_label)
        layout.addWidget(self._scroll, 0)
        _disable_tab_focus(self)

    def _connect_controller(self) -> None:
        if self._signal_connected:
            return
        self._controller.queue_changed.connect(self._schedule_refresh_table)
        self._controller.queue_changed.connect(self._update_header_status)
        self._controller.jobs_pane_title_changed.connect(self._update_header_status)
        self._controller.hold_job_queue_changed.connect(self._update_header_status)
        self._signal_connected = True
        self._controller.task_status_info_changed.connect(
            lambda: self._refresh_active_row(force=True)
        )
        timer = QTimer(self)
        timer.setInterval(500)
        timer.timeout.connect(self._on_live_refresh_timer)
        timer.start()
        self._live_timer = timer
        self._update_header_status()

    def _on_live_refresh_timer(self) -> None:
        if self._imagegen_dialog_building_active():
            return
        if not self._controller.task_status_display_needs_refresh():
            return
        prev_strip_h = 0
        if hasattr(self, "_active_job_strip") and self._active_job_strip.isVisible():
            prev_strip_h = self._active_job_strip.height()
        self._refresh_active_row(force=True)
        self._active_job_strip.refresh(force=True)
        self._controller.mark_task_status_display_refreshed()
        if self._queue_size_mode in (QUEUE_SIZE_STRIP, QUEUE_SIZE_ONE):
            new_strip_h = (
                self._active_job_strip.height()
                if self._active_job_strip.isVisible()
                else 0
            )
            if abs(new_strip_h - prev_strip_h) > 1:
                self._on_active_strip_content_height_changed()

    def pause_live_refresh(self) -> None:
        """Pause periodic refresh while image-gen dialog builds on the GUI thread."""
        self._live_refresh_paused = True
        if self._live_timer is not None:
            self._live_timer.stop()

    def resume_live_refresh(self) -> None:
        self._live_refresh_paused = False
        if self.isVisible() and self._live_timer is not None:
            self._live_timer.start()

    def _imagegen_dialog_building_active(self) -> bool:
        if getattr(self, "_live_refresh_paused", False):
            return True
        main_window = self.main_window
        return bool(getattr(main_window, "_imagegen_dialog_building", False))

    def _update_header_status(self) -> None:
        header = self._jobs_header()
        if header is None:
            return
        if hasattr(header, "set_title_suffix"):
            header.set_title_suffix(self._controller.jobs_pane_title_suffix())
        if hasattr(header, "set_status_text"):
            header.set_status_text(jobs_header_status_text(self._controller))

    def refresh_header_status(self) -> None:
        self._update_header_status()

    def refresh_theme_styles(self) -> None:
        """Reapply theme colors to empty state and job cards."""
        t = get_active_theme()
        _apply_empty_queue_label_style(
            self._empty_label, t.sidebar_text_color_hex
        )
        if hasattr(self, "_scroll"):
            self._scroll.setStyleSheet(t.sidebar_jobs_scroll_stylesheet())
            apply_scroll_area_viewport_background(
                self._scroll, t.sidebar_background_color_hex
            )
        for card in self._job_cards:
            card.setStyleSheet(
                _job_card_stylesheet(selected=card._selected)
            )
        if hasattr(self, "_action_bar"):
            self._action_bar.refresh_theme_styles()
        self._active_job_strip.refresh_theme_styles()
        header = self._jobs_header()
        if header is not None:
            from theme.titlebar_icons import refresh_header_titlebar_icons

            refresh_header_titlebar_icons(header)
        refresh_jobs_flyout_buttons(self.main_window)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        old = event.oldSize()
        new = event.size()
        # Avoid strip reflow feedback when the parent only tweaks height in ALL mode.
        if (
            self._queue_size_mode == QUEUE_SIZE_ALL
            and old.width() == new.width()
            and old.height() != new.height()
        ):
            return
        if old.width() != new.width() or self._queue_size_mode != QUEUE_SIZE_ALL:
            self._refresh_active_job_strip(force=True)

    def sizeHint(self) -> QSize:
        if self._queue_size_mode == QUEUE_SIZE_ALL:
            w = self.width() if self.width() > 0 else -1
            h = self.height() if self.height() > 0 else MIN_JOBS_QUEUE_CONTENT_HEIGHT
            return QSize(w, h)
        return super().sizeHint()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._schedule_refresh_table()
        self._update_header_status()
        self._refresh_active_job_strip(force=True)
        if self._live_timer is not None:
            self._live_timer.start()

    def hideEvent(self, event) -> None:
        if self._live_timer is not None:
            self._live_timer.stop()
        super().hideEvent(event)

    def mousePressEvent(self, event) -> None:
        if isinstance(event, QMouseEvent) and self._try_start_floating_client_drag(
            event, self
        ):
            return
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:
        if isinstance(event, QMouseEvent) and self._try_handle_floating_client_double_click(
            event, self
        ):
            return
        super().mouseDoubleClickEvent(event)

    def eventFilter(self, obj, event) -> bool:
        if isinstance(event, QMouseEvent) and obj in self._floating_drag_filter_targets:
            if (
                event.type() == QEvent.Type.MouseButtonDblClick
                and self._try_handle_floating_client_double_click(event, obj)
            ):
                return True
            if (
                event.type() == QEvent.Type.MouseButtonPress
                and self._try_start_floating_client_drag(event, obj)
            ):
                return True
        if (
            hasattr(self, "_scroll")
            and obj is self._scroll.viewport()
            and event.type() == QEvent.Type.Resize
        ):
            self._schedule_reflow()
            self._refresh_active_job_strip(force=True)
            if self._drop_indicator_index is not None:
                self._show_drop_indicator(self._drop_indicator_index)
        if (
            hasattr(self, "_scroll")
            and obj is self._scroll.viewport()
            and event.type() in (QEvent.Type.DragEnter, QEvent.Type.DragMove)
        ):
            mime = event.mimeData()  # type: ignore[union-attr]
            if mime.hasFormat(_JOB_QUEUE_DRAG_MIME):
                mouse = event  # type: ignore[assignment]
                host_pos = self._list_host.mapFrom(
                    self._scroll.viewport(), mouse.position().toPoint()
                )
                self._show_drop_indicator(
                    self._insert_index_at_list_y(int(host_pos.y()))
                )
                event.acceptProposedAction()
                return True
        if hasattr(self, "_list_host") and obj is self._list_host:
            if event.type() == QEvent.Type.DragEnter:
                if event.mimeData().hasFormat(_JOB_QUEUE_DRAG_MIME):
                    mouse = event  # type: ignore[assignment]
                    self._show_drop_indicator(
                        self._insert_index_at_list_y(int(mouse.position().y()))
                    )
                    event.acceptProposedAction()
                    return True
            if event.type() == QEvent.Type.DragMove:
                if event.mimeData().hasFormat(_JOB_QUEUE_DRAG_MIME):
                    mouse = event  # type: ignore[assignment]
                    self._show_drop_indicator(
                        self._insert_index_at_list_y(int(mouse.position().y()))
                    )
                    event.acceptProposedAction()
                    return True
            if event.type() == QEvent.Type.Drop:
                if event.mimeData().hasFormat(_JOB_QUEUE_DRAG_MIME):
                    payload = bytes(
                        event.mimeData().data(_JOB_QUEUE_DRAG_MIME)
                    ).decode("utf-8")
                    if payload:
                        self._clear_drop_indicator()
                        self._on_job_reorder_drop(payload, len(self._job_cards))
                    event.acceptProposedAction()
                    return True
        return super().eventFilter(obj, event)

    def _schedule_reflow(self) -> None:
        timer = self._resize_timer
        if timer is None:
            timer = QTimer(self)
            timer.setSingleShot(True)
            timer.timeout.connect(self._reflow_all_and_notify)
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
        return max(80, w - 8)

    def _info_content_width(self) -> int:
        return max(80, self._viewport_width() - _CARD_CONTENT_MARGIN)

    def _refresh_active_job_strip(self, *, force: bool = False) -> None:
        if not hasattr(self, "_active_job_strip"):
            return
        if not self.isVisible() or not self._controller.is_running():
            if self._active_job_strip.isVisible():
                self._active_job_strip.hide()
            self._notify_shell_geometry_changed()
            return
        self._active_job_strip.refresh(force=force)

    def _on_active_strip_content_height_changed(self) -> None:
        if self._queue_size_mode == QUEUE_SIZE_ONE:
            self._apply_one_job_scroll_height()
        self._sync_fixed_panel_geometry()
        self._notify_shell_geometry_changed()

    def queue_size_mode(self) -> str:
        return self._queue_size_mode

    def set_queue_size_mode(self, mode: str) -> None:
        """all: every job row; one: active strip + first row; strip: progress strip only."""
        if mode not in _QUEUE_SIZE_MODES:
            mode = QUEUE_SIZE_ALL
        if mode == self._queue_size_mode:
            if mode != QUEUE_SIZE_ALL or self.should_shrink_wrap_client():
                self._sync_fixed_panel_geometry()
            return
        self._queue_size_mode = mode
        self._apply_queue_size_layout()

    def set_queue_compact(self, compact: bool) -> None:
        """Sidebar compact toggle: strip-only vs show queue list."""
        self.set_queue_size_mode(QUEUE_SIZE_STRIP if compact else QUEUE_SIZE_ALL)

    def is_queue_compact(self) -> bool:
        return self._queue_size_mode == QUEUE_SIZE_STRIP

    def prepare_size_measure(self) -> None:
        """Flush layout so fit-to-content height measurements are stable."""
        if self._preparing_size_measure:
            return
        self._preparing_size_measure = True
        try:
            self._refresh_active_job_strip(force=True)
            self._reflow_all()
            app = QApplication.instance()
            if app is not None:
                app.processEvents(QEventLoop.ProcessEventsFlag.ExcludeUserInputEvents)
        finally:
            self._preparing_size_measure = False

    def refresh_compact_geometry(self, strip_h: int | None = None) -> None:
        """Re-pin widget height to the strip (strip mode / sidebar compact)."""
        if not self.is_queue_compact():
            return
        if strip_h is not None:
            self.setSizePolicy(
                QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
            )
            self.setFixedHeight(strip_h)
            self.updateGeometry()
            return
        self._sync_fixed_panel_geometry()

    def _sync_fixed_panel_geometry(self) -> None:
        if self._queue_size_mode == QUEUE_SIZE_ALL and not self.should_shrink_wrap_client():
            return
        content_h = self.content_height_for_size_mode()
        if self.height() == content_h:
            return
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        if content_h < self.height():
            self.setMinimumHeight(0)
            self.setMaximumHeight(16777215)
        self.setFixedHeight(content_h)
        self.setMaximumHeight(content_h)
        self.updateGeometry()

    def _apply_panel_layout_stretch(self) -> None:
        layout = getattr(self, "_panel_layout", None)
        if layout is None:
            return
        shrink = self.should_shrink_wrap_client()
        if self._queue_size_mode == QUEUE_SIZE_ALL and not shrink:
            layout.setStretchFactor(self._scroll, 1)
            self._scroll.setSizePolicy(
                QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
            )
            self._scroll.setMinimumHeight(0)
            self._scroll.setMaximumHeight(16777215)
        else:
            layout.setStretchFactor(self._scroll, 0)
            self._scroll.setSizePolicy(
                QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
            )
            self._scroll.setFixedHeight(0)
            self._scroll.setMaximumHeight(0)

    def _apply_one_job_scroll_height(self) -> None:
        if not self._job_cards:
            self._scroll.setFixedHeight(0)
            return
        margins = self._list_layout.contentsMargins()
        card_h = self._job_cards[0].minimumHeight()
        self._scroll.setFixedHeight(card_h + margins.top() + margins.bottom())

    def _apply_queue_size_layout(self) -> None:
        has_rows = bool(self._job_cards)
        mode = self._queue_size_mode
        self._apply_panel_layout_stretch()
        if self._should_show_action_bar():
            self._action_bar.show()
            self._action_bar.update_for_row(
                self._controller.resolve_selected_row_index()
            )
        else:
            self._action_bar.hide()

        if mode == QUEUE_SIZE_STRIP:
            self._scroll.hide()
            for card in self._job_cards:
                card.hide()
            if self._controller.is_running():
                self._active_job_strip.refresh(force=True)
                self._empty_label.hide()
            else:
                self._empty_label.setVisible(not has_rows)
            self._sync_fixed_panel_geometry()
        elif mode == QUEUE_SIZE_ONE:
            self._empty_label.setVisible(not has_rows)
            self._scroll.setVisible(has_rows)
            self._scroll.setVerticalScrollBarPolicy(
                Qt.ScrollBarPolicy.ScrollBarAlwaysOff
            )
            for idx, card in enumerate(self._job_cards):
                card.setVisible(idx == 0)
            if has_rows:
                self._apply_one_job_scroll_height()
            else:
                self._scroll.setFixedHeight(0)
            self._sync_fixed_panel_geometry()
        else:
            self.setMinimumHeight(0)
            self.setMaximumHeight(16777215)
            self.setSizePolicy(
                QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
            )
            self._scroll.setMinimumHeight(0)
            self._scroll.setMaximumHeight(16777215)
            self._scroll.setVerticalScrollBarPolicy(
                Qt.ScrollBarPolicy.ScrollBarAsNeeded
            )
            for card in self._job_cards:
                card.show()
            self._empty_label.setVisible(not has_rows)
            self._scroll.setVisible(has_rows)
            if self.should_shrink_wrap_client():
                self._sync_fixed_panel_geometry()
        self.updateGeometry()

    def _active_strip_block_height(self) -> int:
        if not self._controller.is_running():
            return 0
        if self._active_job_strip.isVisible() and self._active_job_strip.height() > 0:
            return self._active_job_strip.height()
        return self._active_job_strip.content_height()

    def strip_only_content_height(self) -> int:
        """Client height for strip-only view (progress container)."""
        if self._controller.is_running():
            self._active_job_strip.refresh(force=True)
            if self._active_job_strip.isVisible():
                h = self._active_job_strip.height()
                if h > 0:
                    return h
        strip_h = self._active_job_strip.content_height()
        if strip_h > 0:
            return strip_h
        if not self._job_cards:
            return self.empty_state_height_hint()
        return MIN_JOBS_QUEUE_CONTENT_HEIGHT

    def _measure_first_job_card_height(self) -> int:
        if not self._job_cards:
            return 0
        info_w = self._info_content_width()
        width = self._viewport_width()
        card = self._job_cards[0]
        rows = self._controller.queue_snapshot()
        row = rows[0] if rows else None
        if card._last_info_html:
            card.update_info_html(card._last_info_html, info_w, scroll_width=width)
        elif row is not None:
            card.update_info_html(
                info_html_for_queue_row(
                    self._controller, 0, row, for_sidebar=True
                ),
                info_w,
                scroll_width=width,
            )
            if row.thumbnail_paths:
                card._replace_refs(row.thumbnail_paths, info_w, scroll_width=width)
        else:
            card.reflow_refs(width)
            return card.minimumHeight()
        card.reflow_refs(width)
        return card.minimumHeight()

    def single_job_content_height(self) -> int:
        """Client height for one job row (+ active strip when running)."""
        total = self._active_strip_block_height()
        if not self._job_cards:
            return total + self.empty_state_height_hint()
        margins = self._list_layout.contentsMargins()
        return (
            total
            + self._action_bar_block_height()
            + margins.top()
            + margins.bottom()
            + self._measure_first_job_card_height()
        )

    def content_height_for_size_mode(self, mode: str | None = None) -> int:
        mode = mode or self._queue_size_mode
        if mode == QUEUE_SIZE_STRIP:
            return self.strip_only_content_height()
        if mode == QUEUE_SIZE_ONE:
            return self.single_job_content_height()
        return self.preferred_content_height()

    def minimumSizeHint(self) -> QSize:
        if self._queue_size_mode != QUEUE_SIZE_ALL:
            return QSize(0, self.content_height_for_size_mode())
        if self.should_shrink_wrap_client():
            return QSize(0, self.empty_state_height_hint())
        return QSize(0, MIN_JOBS_QUEUE_CONTENT_HEIGHT)

    def _refresh_active_row(self, *, force: bool = False) -> None:
        if not force and self._imagegen_dialog_building_active():
            return
        if not self.isVisible() or not self._job_cards:
            return
        if not force and not self._controller.task_status_display_needs_refresh():
            return
        rows = self._controller.queue_snapshot()
        if not rows or not rows[0].is_active:
            return
        row = rows[0]
        info_html = info_html_for_queue_row(
            self._controller, 0, row, for_sidebar=True
        )
        info_w = self._info_content_width()
        viewport_w = self._viewport_width()
        self._job_cards[0]._full_prompt = row.full_prompt or ""
        update_delayed_prompt_tooltip(
            self._job_cards[0]._info_browser, self._job_cards[0]._full_prompt
        )
        self._job_cards[0].update_info_html(info_html, info_w, scroll_width=viewport_w)
        self._job_cards[0]._replace_refs(
            row.thumbnail_paths, info_w, scroll_width=viewport_w
        )
        self._job_cards[0].reflow_refs(viewport_w)
        _disable_tab_focus(self._job_cards[0])
        if self._queue_size_mode == QUEUE_SIZE_ONE:
            self._apply_one_job_scroll_height()
            self._sync_fixed_panel_geometry()

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
                card.update_info_html(
                    card._last_info_html, info_w, scroll_width=width
                )
            card.reflow_refs(width)
        if self._queue_size_mode == QUEUE_SIZE_ONE:
            self._apply_one_job_scroll_height()
            self._sync_fixed_panel_geometry()
        elif self._queue_size_mode == QUEUE_SIZE_STRIP:
            self._sync_fixed_panel_geometry()

    def _reflow_all_and_notify(self) -> None:
        self._reflow_all()
        self._notify_shell_geometry_changed()

    def _notify_shell_geometry_changed(self) -> None:
        if self._preparing_size_measure:
            return
        cb = self._on_compact_geometry_changed
        if cb is not None:
            cb()

    def compact_content_height(self) -> int:
        """Client height for minimized view: active progress strip only."""
        return self._active_job_strip.content_height()

    def preferred_content_height(self) -> int:
        """Height needed to show all job rows without vertical scrolling."""
        total = 0
        if (
            hasattr(self, "_active_job_strip")
            and self._active_job_strip.isVisible()
        ):
            strip_h = self._active_job_strip.height()
            total += strip_h if strip_h > 0 else self._active_job_strip.sizeHint().height()
        if not self._job_cards:
            return total + self.empty_state_height_hint()
        total += self._action_bar_block_height()
        info_w = self._info_content_width()
        width = self._viewport_width()
        rows = self._controller.queue_snapshot()
        margins = self._list_layout.contentsMargins()
        total += margins.top() + margins.bottom()
        spacing = self._list_layout.spacing()
        for row_idx, card in enumerate(self._job_cards):
            if row_idx > 0:
                total += spacing
            row = rows[row_idx] if row_idx < len(rows) else None
            if card._last_info_html:
                card.update_info_html(
                    card._last_info_html, info_w, scroll_width=width
                )
            elif row is not None:
                card.update_info_html(
                    info_html_for_queue_row(
                        self._controller, row_idx, row, for_sidebar=True
                    ),
                    info_w,
                    scroll_width=width,
                )
                if row.thumbnail_paths:
                    card._replace_refs(
                        row.thumbnail_paths, info_w, scroll_width=width
                    )
            else:
                card.reflow_refs(width)
                total += self._card_layout_height(card)
                continue
            card.reflow_refs(width)
            total += self._card_layout_height(card)
        return total

    def refresh_table(self) -> None:
        rows = self._controller.queue_snapshot()
        self._clear_drop_indicator()
        self._clear_job_cards()

        info_w = self._info_content_width()
        viewport_w = self._viewport_width()
        for row_idx, row in enumerate(rows):
            info_html = info_html_for_queue_row(
                self._controller, row_idx, row, for_sidebar=True
            )
            card = JobCard(
                self.main_window,
                self._controller,
                row_idx,
                job_id=row.job_id,
                is_active=row.is_active,
                on_select=self._on_job_selected,
                on_reorder_drop=self._on_job_reorder_drop,
                on_drop_hover=self._show_drop_indicator,
                on_drop_hover_clear=self._clear_drop_indicator,
            )
            card.set_row_content(
                info_html=info_html,
                full_prompt=row.full_prompt,
                thumbnail_paths=row.thumbnail_paths,
                content_width=info_w,
                scroll_width=viewport_w,
                references_invalid=row.references_invalid,
            )
            self._list_layout.insertWidget(self._list_layout.count() - 1, card)
            self._job_cards.append(card)
            _disable_tab_focus(card)

        self._controller.resolve_selected_row_index()
        self._reflow_all()
        _disable_tab_focus(self)
        self._sync_selection_ui()
        self._update_header_status()
        self._refresh_active_job_strip(force=True)
        self._apply_queue_size_layout()
        self._notify_shell_geometry_changed()
