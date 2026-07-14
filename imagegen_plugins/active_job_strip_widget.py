#!/usr/bin/env python3
"""Live-updating active job progress strip (shared by jobs pane, panel, and quit prompts)."""

from __future__ import annotations

from PySide6.QtCore import QEvent, Qt, QTimer
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QSizePolicy,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from imagegen_plugins.image_gen_controller import get_imagegen_controller
from imagegen_plugins.model_task_status_info import (
    _ACTIVE_JOB_STRIP_FRAME_CHROME_V,
    active_job_strip_layout_widths,
    build_active_job_timing_cell_html,
    wrap_active_job_timing_table_html,
)
from status_bar_config import (
    _wrap_task_info_html,
    handle_task_info_reference_link_clicked,
)
from theme.theme_service import get_active_theme

_ACTIVE_JOB_STRIP_MARGIN = 8  # left + right QLayout margins on the strip (4+4)


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


def _disable_tab_focus(root: QWidget) -> None:
    root.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    for child in root.findChildren(QWidget):
        child.setFocusPolicy(Qt.FocusPolicy.NoFocus)


class ActiveJobStripWidget(QWidget):
    """Bordered progress strip for the active generation/caption job."""

    def __init__(
        self,
        main_window,
        parent=None,
        *,
        pause_when_imagegen_dialog_building: bool = True,
        layout_width_px: int | None = None,
    ):
        super().__init__(parent)
        self.main_window = main_window
        self._controller = get_imagegen_controller(main_window)
        self._pause_when_imagegen_dialog_building = bool(
            pause_when_imagegen_dialog_building
        )
        self._layout_width_px = layout_width_px
        self._active_job_hovered_anchor: str | None = None
        self._live_timer: QTimer | None = None
        self._setup_ui()
        self._connect_controller()

    def _setup_ui(self) -> None:
        h_policy = (
            QSizePolicy.Policy.Preferred
            if self._layout_width_px is not None
            else QSizePolicy.Policy.Expanding
        )
        self.setSizePolicy(h_policy, QSizePolicy.Policy.Fixed)
        if self._layout_width_px is not None:
            self.setMaximumWidth(self._layout_width_px)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 0)
        layout.setSpacing(0)
        self._frame = QFrame()
        self._frame.setObjectName("activeJobStripFrame")
        self._frame.setStyleSheet(_active_job_strip_frame_stylesheet())
        frame_layout = QVBoxLayout(self._frame)
        frame_layout.setContentsMargins(0, 0, 0, 0)
        frame_layout.setSpacing(0)
        self._browser = QTextBrowser()
        self._browser.setReadOnly(True)
        self._browser.setOpenExternalLinks(False)
        self._browser.setOpenLinks(False)
        self._browser.setFrameShape(QTextBrowser.Shape.NoFrame)
        self._browser.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._browser.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self._browser.setStyleSheet(_active_job_strip_browser_stylesheet())
        self._browser.anchorClicked.connect(
            lambda url: handle_task_info_reference_link_clicked(self.main_window, url)
        )
        self._browser.setSizePolicy(
            QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed
        )
        self._viewport = self._browser.viewport()
        self._viewport.setMouseTracking(True)
        self._viewport.installEventFilter(self)
        frame_layout.addWidget(
            self._browser,
            0,
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop,
        )
        layout.addWidget(
            self._frame,
            0,
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop,
        )
        self.hide()

    def _connect_controller(self) -> None:
        self._controller.generation_started.connect(lambda: self.refresh(force=True))
        self._controller.generation_finished.connect(self.refresh)
        self._controller.task_status_info_changed.connect(
            lambda: self.refresh(force=True)
        )
        timer = QTimer(self)
        timer.setInterval(500)
        timer.timeout.connect(self._on_live_refresh_timer)
        self._live_timer = timer

    def _imagegen_dialog_building_active(self) -> bool:
        if not self._pause_when_imagegen_dialog_building:
            return False
        main_window = self.main_window
        return bool(getattr(main_window, "_imagegen_dialog_building", False))

    def set_layout_width_px(self, width_px: int) -> None:
        width_px = max(80, int(width_px))
        if width_px == self._layout_width_px:
            return
        self._layout_width_px = width_px
        self.setMaximumWidth(width_px)
        self.refresh(force=True)

    def _strip_min_frame_width(self) -> int:
        return 80

    def _layout_content_width(self) -> int:
        if self._layout_width_px is not None:
            return max(0, self._layout_width_px - _ACTIVE_JOB_STRIP_MARGIN)
        w = self.width()
        if w <= 0:
            parent = self.parentWidget()
            if parent is not None:
                w = parent.width()
        return max(0, w - _ACTIVE_JOB_STRIP_MARGIN)

    def _layout_widths(self) -> tuple[int, int]:
        return active_job_strip_layout_widths(
            self._layout_content_width(),
            min_frame_width_px=self._strip_min_frame_width(),
        )

    def _on_live_refresh_timer(self) -> None:
        if self._imagegen_dialog_building_active():
            return
        if not self.isVisible():
            return
        if not self._controller.task_status_display_needs_refresh():
            return
        self.refresh(force=True)
        self._controller.mark_task_status_display_refreshed()

    def refresh(self, *, force: bool = False) -> None:
        if not force and self._imagegen_dialog_building_active():
            return
        if not self._controller.is_running():
            self.hide()
            return
        if not force and not self._controller.task_status_display_needs_refresh():
            return
        frame_w, browser_w = self._layout_widths()
        hovered = self._active_job_hovered_anchor
        cell_html = build_active_job_timing_cell_html(
            self._controller,
            content_width_px=browser_w,
            cancel_hovered=hovered == "cancelgen://",
            skip_hovered=hovered == "skipcooldown://",
        )
        if not cell_html:
            self.hide()
            return
        body_html = wrap_active_job_timing_table_html(
            cell_html, content_width_px=browser_w
        )
        browser_h = _apply_active_job_strip_html(
            self._browser,
            body_html,
            content_width=browser_w,
        )
        self._frame.setFixedWidth(frame_w)
        self._frame.setFixedHeight(browser_h + _ACTIVE_JOB_STRIP_FRAME_CHROME_V)
        layout = self.layout()
        margin_h = 0
        if layout is not None:
            margins = layout.contentsMargins()
            margin_h = margins.top() + margins.bottom()
        self.setFixedHeight(self._frame.height() + margin_h)
        self.show()
        _disable_tab_focus(self)

    def content_height(self) -> int:
        """Height when visible, or estimated height for compact layout."""
        if not self._controller.is_running():
            return 0
        if self.isVisible() and self.height() > 0:
            return self.height()
        frame_w, browser_w = self._layout_widths()
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
            self._browser,
            body_html,
            content_width=browser_w,
        )
        layout = self.layout()
        if layout is None:
            return browser_h + _ACTIVE_JOB_STRIP_FRAME_CHROME_V
        margins = layout.contentsMargins()
        return browser_h + _ACTIVE_JOB_STRIP_FRAME_CHROME_V + margins.top() + margins.bottom()

    def refresh_theme_styles(self) -> None:
        self._browser.setStyleSheet(_active_job_strip_browser_stylesheet())
        self._frame.setStyleSheet(_active_job_strip_frame_stylesheet())
        self.refresh(force=True)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self._layout_width_px is None:
            self.refresh(force=True)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.refresh(force=True)
        if self._live_timer is not None:
            self._live_timer.start()

    def hideEvent(self, event) -> None:
        if self._live_timer is not None:
            self._live_timer.stop()
        super().hideEvent(event)

    def eventFilter(self, obj, event) -> bool:
        if obj is self._viewport:
            if event.type() == QEvent.Type.MouseMove:
                pos = (
                    event.position().toPoint()
                    if hasattr(event, "position")
                    else event.pos()
                )
                anchor = self._browser.anchorAt(pos)
                if anchor != self._active_job_hovered_anchor:
                    self._active_job_hovered_anchor = anchor or None
                    self.refresh(force=True)
            elif event.type() == QEvent.Type.Leave:
                if self._active_job_hovered_anchor is not None:
                    self._active_job_hovered_anchor = None
                    self.refresh(force=True)
        return super().eventFilter(obj, event)
