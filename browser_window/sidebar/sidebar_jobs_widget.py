#!/usr/bin/env python3
"""Job queue list for the right combined sidebar Jobs pane (matches dialog data)."""

from __future__ import annotations

import os

from PySide6.QtCore import QEvent, Qt, QTimer, QSize, QPoint
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
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

from imagegen_plugins.image_gen_controller import get_imagegen_controller
from imagegen_plugins.image_gen_job_queue_dialog import (
    _ACTION_COL_WIDTH,
    _apply_job_queue_cell_background,
    _valid_preview_paths,
    build_job_queue_action_widget,
    create_invalid_job_preview_label,
    info_html_for_queue_row,
    open_reference_thumbnail_paths,
)
from config import job_queue_cell_background_hex
from imagegen_plugins.job_prompt_tooltip import (
    install_delayed_prompt_tooltip,
    update_delayed_prompt_tooltip,
)
from imagegen_plugins.model_task_status_info import (
    _ACTIVE_JOB_STRIP_FRAME_CHROME_V,
    active_job_strip_layout_widths,
    build_active_job_timing_cell_html,
    wrap_active_job_timing_table_html,
)
from status_bar_config import (
    _apply_task_info_html_to_browser,
    _wrap_task_info_html,
    configure_task_info_text_browser,
    handle_task_info_reference_link_clicked,
)
from theme.theme_base import job_pane_tools_icon_path
from theme.theme_service import get_active_theme
from browser_window.sidebar.sidebar_pane_chrome import apply_scroll_area_viewport_background
from thumbnails.sidebar_pane_layout import MIN_JOBS_QUEUE_CONTENT_HEIGHT
from utils import create_job_status_thumbnail_label

_THUMB_SIZE = 55
_THUMB_GAP = 14
_ACTIVE_JOB_STRIP_MARGIN = 8  # left + right QLayout margins on the strip (4+4)

# When scroll viewport width exceeds this and a row has 1–2 reference images, show
# them in a vertical column beside the text instead of below it.
JOB_CELL_INLINE_REFS_MIN_SCROLL_WIDTH = 350
JOB_CELL_INLINE_REFS_RIGHT_PADDING_PX = 2
_JOB_CELL_INLINE_TEXT_REFS_SPACING = 4


def _active_job_strip_browser_stylesheet() -> str:
    t = get_active_theme()
    return f"""
        QTextBrowser {{
            color: {t.sidebar_text_color_hex};
            background: transparent;
            padding: 0;
            margin: 0;
            border: none;
        }}
    """


def _active_job_strip_frame_stylesheet() -> str:
    t = get_active_theme()
    bdr = t.default_border_color_hex
    return f"""
        QFrame#activeJobStripFrame {{
            border: 1px solid {bdr};
            padding: 4px;
            background: transparent;
        }}
    """


def _apply_active_job_strip_html(
    browser: QTextBrowser, body_html: str, *, content_width: int
) -> int:
    """Size the active-job strip browser to the bordered table (no trailing fill box)."""
    browser.setFixedWidth(content_width)
    browser.setHtml(_wrap_task_info_html(body_html))
    browser.document().setDocumentMargin(0)
    browser.document().setTextWidth(content_width)
    doc = browser.document()
    layout_h = doc.documentLayout().documentSize().height()
    doc_h = doc.size().height()
    content_h = max(doc_h, layout_h, browser.fontMetrics().lineSpacing())
    height = int(max(content_h, 28) + 2)
    browser.setFixedHeight(height)
    browser.setMinimumHeight(height)
    return height


def _jobs_header_status_text(controller) -> str:
    """Title-bar queue summary: waiting jobs only."""
    waiting = sum(1 for row in controller.queue_snapshot() if not row.is_active)
    if waiting > 0:
        return f"+{waiting} "
    return ""


def _jobs_header(main_window):
    right_sidebar = getattr(main_window, "right_sidebar", None)
    if right_sidebar is None:
        return None
    return getattr(right_sidebar, "jobs_header", None)


def _update_jobs_header_status(main_window, controller) -> None:
    header = _jobs_header(main_window)
    if header is None:
        return
    header.set_title_suffix(controller.jobs_pane_title_suffix())
    header.set_status_text(_jobs_header_status_text(controller))


def _show_jobs_pane_tools_menu(main_window, controller, anchor: QPushButton) -> None:
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

    skip_copy_action = menu.addAction("Skip This Copy")
    skip_copy_action.setEnabled(controller.can_skip_active_series_copy())
    skip_copy_action.setToolTip(
        "End the current copy and start the next one in this series."
    )
    skip_copy_action.triggered.connect(controller.skip_active_series_copy)

    menu.exec(anchor.mapToGlobal(QPoint(0, anchor.height())))


def _setup_jobs_titlebar_tools(main_window, controller) -> None:
    header = _jobs_header(main_window)
    if header is None:
        return
    btn = QPushButton()
    btn.setIcon(QIcon(job_pane_tools_icon_path()))
    btn.setIconSize(QSize(14, 14))
    btn.setToolTip("Job queue tools")
    btn.clicked.connect(
        lambda: _show_jobs_pane_tools_menu(main_window, controller, btn)
    )
    header.set_tools_button(btn)


def _disable_tab_focus(root: QWidget) -> None:
    """Keep job pane controls out of the keyboard tab order."""
    root.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    for child in root.findChildren(QWidget):
        child.setFocusPolicy(Qt.FocusPolicy.NoFocus)


def _job_card_stylesheet() -> str:
    t = get_active_theme()
    bg = job_queue_cell_background_hex()
    return f"""
        QFrame#sidebarJobCard {{
            background-color: {bg};
            color: {t.sidebar_text_color_hex};
            border: 1px solid {t.border_default_hex};
            border-radius: 4px;
        }}
    """


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
        self._scroll_width = 0
        self._content_inline = False

        row_layout = QHBoxLayout(self)
        row_layout.setContentsMargins(2, 2, 2, 2)
        row_layout.setSpacing(4)

        self._actions = build_job_queue_action_widget(
            main_window,
            controller,
            row_idx,
            is_active=is_active,
        )
        row_layout.addWidget(self._actions, 0, Qt.AlignmentFlag.AlignTop)

        self._content = QWidget()
        _apply_job_queue_cell_background(self._content)

        self._info_browser = QTextBrowser()
        configure_task_info_text_browser(
            self._info_browser, main_window, job_queue_cell=True
        )
        self._info_browser.setSizePolicy(
            QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed
        )

        self._refs = _FlowReferenceThumbs(main_window, [])
        self._ensure_content_layout(False)
        row_layout.addWidget(self._content, 1)

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
        scroll_width: int,
        references_invalid: bool = False,
    ) -> None:
        self._scroll_width = scroll_width
        self._full_prompt = full_prompt or ""
        install_delayed_prompt_tooltip(self._info_browser, self._full_prompt)
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
            else self._scroll_width or (content_width + _ACTION_COL_WIDTH + 20)
        )
        self._scroll_width = sw
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
            else self._scroll_width or (content_width + _ACTION_COL_WIDTH + 20)
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
        content_width = max(80, scroll_width - _ACTION_COL_WIDTH - 20)
        self._scroll_width = scroll_width
        self._ensure_content_layout(self._use_inline_refs_layout(scroll_width))
        if self._last_info_html:
            self.update_info_html(
                self._last_info_html, content_width, scroll_width=scroll_width
            )
        else:
            self._reflow_visible_refs(content_width, scroll_width)
            self._sync_card_height(content_width, scroll_width=scroll_width)


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
        self._active_job_hovered_anchor: str | None = None
        self._queue_compact = False
        self._signal_connected = False
        self._live_refresh_paused = False
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
            f"color: {t.sidebar_text_color_hex}; font-size: 12px; padding: 12px;"
        )

        self._active_job_strip = QWidget()
        active_job_layout = QHBoxLayout(self._active_job_strip)
        active_job_layout.setContentsMargins(4, 4, 4, 0)
        active_job_layout.setSpacing(0)
        self._active_job_frame = QFrame()
        self._active_job_frame.setObjectName("activeJobStripFrame")
        self._active_job_frame.setStyleSheet(_active_job_strip_frame_stylesheet())
        frame_layout = QVBoxLayout(self._active_job_frame)
        frame_layout.setContentsMargins(0, 0, 0, 0)
        frame_layout.setSpacing(0)
        self._active_job_browser = QTextBrowser()
        self._active_job_browser.setReadOnly(True)
        self._active_job_browser.setOpenExternalLinks(False)
        self._active_job_browser.setOpenLinks(False)
        self._active_job_browser.setFrameShape(QTextBrowser.Shape.NoFrame)
        self._active_job_browser.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self._active_job_browser.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self._active_job_browser.setStyleSheet(_active_job_strip_browser_stylesheet())
        self._active_job_browser.anchorClicked.connect(
            lambda url: handle_task_info_reference_link_clicked(self.main_window, url)
        )
        self._active_job_browser.setSizePolicy(
            QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed
        )
        self._active_job_viewport = self._active_job_browser.viewport()
        self._active_job_viewport.setMouseTracking(True)
        self._active_job_viewport.installEventFilter(self)
        frame_layout.addWidget(
            self._active_job_browser,
            0,
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop,
        )
        active_job_layout.addWidget(
            self._active_job_frame,
            0,
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop,
        )
        self._active_job_strip.hide()

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
        self._list_layout = QVBoxLayout(self._list_host)
        self._list_layout.setContentsMargins(4, 4, 4, 4)
        self._list_layout.setSpacing(8)
        self._list_layout.addStretch(1)

        self._scroll.setWidget(self._list_host)
        layout.addWidget(self._active_job_strip)
        layout.addWidget(self._empty_label)
        layout.addWidget(self._scroll, 1)
        _disable_tab_focus(self)

    def _connect_controller(self) -> None:
        if self._signal_connected:
            return
        self._controller.queue_changed.connect(self._schedule_refresh_table)
        self._controller.queue_changed.connect(self._update_header_status)
        self._controller.jobs_pane_title_changed.connect(self._update_header_status)
        self._controller.generation_started.connect(
            lambda: self._refresh_active_job_strip(force=True)
        )
        self._controller.generation_finished.connect(self._refresh_active_job_strip)
        self._controller.task_status_info_changed.connect(
            lambda: self._refresh_active_row(force=True)
        )
        self._controller.task_status_info_changed.connect(
            lambda: self._refresh_active_job_strip(force=True)
        )
        self._controller.hold_job_queue_changed.connect(self._update_header_status)
        self._signal_connected = True
        timer = QTimer(self)
        timer.setInterval(500)
        timer.timeout.connect(lambda: self._refresh_active_row(force=False))
        timer.timeout.connect(lambda: self._refresh_active_job_strip(force=False))
        timer.start()
        self._live_timer = timer
        self._update_header_status()

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
        _update_jobs_header_status(self.main_window, self._controller)

    def attach_titlebar_tools(self) -> None:
        """Wire the Job Control titlebar tools menu (after right sidebar exists)."""
        _setup_jobs_titlebar_tools(self.main_window, self._controller)

    def refresh_header_status(self) -> None:
        self._update_header_status()

    def refresh_theme_styles(self) -> None:
        """Reapply sidebar theme colors to empty state and job cards."""
        t = get_active_theme()
        self._empty_label.setStyleSheet(
            f"color: {t.sidebar_text_color_hex}; font-size: 12px; padding: 12px;"
        )
        if hasattr(self, "_scroll"):
            self._scroll.setStyleSheet(t.sidebar_jobs_scroll_stylesheet())
            apply_scroll_area_viewport_background(self._scroll, t.sidebar_background_color_hex)
        if hasattr(self, "_active_job_browser"):
            self._active_job_browser.setStyleSheet(_active_job_strip_browser_stylesheet())
        if hasattr(self, "_active_job_frame"):
            self._active_job_frame.setStyleSheet(_active_job_strip_frame_stylesheet())
        card_ss = _job_card_stylesheet()
        for card in self._job_cards:
            card.setStyleSheet(card_ss)
        self._refresh_active_job_strip(force=True)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._refresh_active_job_strip(force=True)

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

    def eventFilter(self, obj, event) -> bool:
        if hasattr(self, "_active_job_viewport") and obj is self._active_job_viewport:
            if event.type() == QEvent.Type.MouseMove:
                pos = (
                    event.position().toPoint()
                    if hasattr(event, "position")
                    else event.pos()
                )
                anchor = self._active_job_browser.anchorAt(pos)
                if anchor != self._active_job_hovered_anchor:
                    self._active_job_hovered_anchor = anchor or None
                    self._refresh_active_job_strip(force=True)
            elif event.type() == QEvent.Type.Leave:
                if self._active_job_hovered_anchor is not None:
                    self._active_job_hovered_anchor = None
                    self._refresh_active_job_strip(force=True)
        if (
            hasattr(self, "_scroll")
            and obj is self._scroll.viewport()
            and event.type() == QEvent.Type.Resize
        ):
            self._schedule_reflow()
            self._refresh_active_job_strip(force=True)
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

    def _active_job_strip_layout_widths(self) -> tuple[int, int]:
        w = self.width() if self.width() > 0 else self._viewport_width()
        return active_job_strip_layout_widths(w - _ACTIVE_JOB_STRIP_MARGIN)

    def _should_show_active_job_strip(self) -> bool:
        return self._controller.is_running()

    def _refresh_active_job_strip(self, *, force: bool = False) -> None:
        if not force and self._imagegen_dialog_building_active():
            return
        if not hasattr(self, "_active_job_strip"):
            return
        visible = self.isVisible() and self._should_show_active_job_strip()
        if not visible:
            if self._active_job_strip.isVisible():
                self._active_job_strip.hide()
            return
        if not force and not self._controller.task_status_display_needs_refresh():
            if self._active_job_strip.isVisible():
                return
        frame_w, browser_w = self._active_job_strip_layout_widths()
        hovered = self._active_job_hovered_anchor
        cell_html = build_active_job_timing_cell_html(
            self._controller,
            content_width_px=browser_w,
            cancel_hovered=hovered == "cancelgen://",
            skip_hovered=hovered == "skipcooldown://",
        )
        if not cell_html:
            self._active_job_strip.hide()
            return
        body_html = wrap_active_job_timing_table_html(
            cell_html, content_width_px=browser_w
        )
        browser_h = _apply_active_job_strip_html(
            self._active_job_browser,
            body_html,
            content_width=browser_w,
        )
        self._active_job_frame.setFixedWidth(frame_w)
        self._active_job_frame.setFixedHeight(browser_h + _ACTIVE_JOB_STRIP_FRAME_CHROME_V)
        layout = self._active_job_strip.layout()
        margin_h = 0
        if layout is not None:
            margins = layout.contentsMargins()
            margin_h = margins.top() + margins.bottom()
        self._active_job_strip.setFixedHeight(self._active_job_frame.height() + margin_h)
        self._active_job_strip.show()
        _disable_tab_focus(self._active_job_strip)
        if self._queue_compact:
            sidebar = getattr(self.main_window, "right_sidebar", None)
            if sidebar is not None and getattr(sidebar, "_jobs_pane_compact", False):
                sidebar._sync_jobs_compact_geometry()

    def set_queue_compact(self, compact: bool) -> None:
        """Minimized pane: hide queue list so only the progress strip sizes the pane."""
        compact = bool(compact)
        if compact == self._queue_compact:
            if compact:
                self.refresh_compact_geometry()
            return
        self._queue_compact = compact
        self._apply_queue_compact_layout()

    def refresh_compact_geometry(self, strip_h: int | None = None) -> None:
        """Re-pin widget height to the strip (compact mode only)."""
        if not self._queue_compact:
            return
        if strip_h is None:
            strip_h = self.compact_content_height()
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        self.setFixedHeight(strip_h)
        self.updateGeometry()

    def _apply_queue_compact_layout(self) -> None:
        has_rows = bool(self._job_cards)
        if self._queue_compact:
            self._scroll.hide()
            self._empty_label.setVisible(not has_rows)
            self.refresh_compact_geometry()
        else:
            self.setMinimumHeight(0)
            self.setMaximumHeight(16777215)
            self.setSizePolicy(
                QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
            )
            self._scroll.setMinimumHeight(0)
            self._empty_label.setVisible(not has_rows)
            self._scroll.setVisible(has_rows)
        self.updateGeometry()

    def minimumSizeHint(self) -> QSize:
        if self._queue_compact:
            return QSize(0, self.compact_content_height())
        # Ignore queue scroll height so the splitter can shrink into compact mode.
        h = 0
        if (
            hasattr(self, "_active_job_strip")
            and self._active_job_strip.isVisible()
        ):
            h = self._active_job_strip.height()
            if h <= 0:
                h = self.compact_content_height()
        elif self._empty_label.isVisible():
            h = self._empty_label.sizeHint().height()
        elif hasattr(self, "_scroll") and self._scroll.isVisible():
            h = MIN_JOBS_QUEUE_CONTENT_HEIGHT
        return QSize(0, h)

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

    def compact_content_height(self) -> int:
        """Client height for minimized pane: active progress strip only."""
        if not self._should_show_active_job_strip():
            return 0
        if (
            hasattr(self, "_active_job_strip")
            and self._active_job_strip.isVisible()
            and self._active_job_strip.height() > 0
        ):
            return self._active_job_strip.height()
        frame_w, browser_w = self._active_job_strip_layout_widths()
        cell_html = build_active_job_timing_cell_html(
            self._controller,
            content_width_px=browser_w,
        )
        if not cell_html:
            return 0
        body_html = wrap_active_job_timing_table_html(
            cell_html, content_width_px=browser_w
        )
        browser_h = _apply_active_job_strip_html(
            self._active_job_browser,
            body_html,
            content_width=browser_w,
        )
        layout = self._active_job_strip.layout()
        if layout is None:
            return browser_h + _ACTIVE_JOB_STRIP_FRAME_CHROME_V
        margins = layout.contentsMargins()
        return browser_h + _ACTIVE_JOB_STRIP_FRAME_CHROME_V + margins.top() + margins.bottom()

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
            return total + self._empty_label.sizeHint().height()
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
            # Measure from cached HTML — do not re-fetch live active-job state here
            # (would flash Steps timing and fight the progress-bar strip).
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
                total += card.minimumHeight()
                continue
            card.reflow_refs(width)
            total += card.minimumHeight()
        return total

    def refresh_table(self) -> None:
        rows = self._controller.queue_snapshot()
        has_rows = bool(rows)
        self._empty_label.setVisible(not has_rows and not self._queue_compact)
        self._scroll.setVisible(has_rows and not self._queue_compact)
        self._clear_job_cards()

        info_w = self._info_content_width()
        viewport_w = self._viewport_width()
        for row_idx, row in enumerate(rows):
            info_html = info_html_for_queue_row(
                self._controller, row_idx, row, for_sidebar=True
            )
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
                scroll_width=viewport_w,
                references_invalid=row.references_invalid,
            )
            self._list_layout.insertWidget(self._list_layout.count() - 1, card)
            self._job_cards.append(card)
            _disable_tab_focus(card)

        self._schedule_reflow()
        _disable_tab_focus(self)
        self._update_header_status()
        self._refresh_active_job_strip(force=True)
