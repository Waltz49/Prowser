#!/usr/bin/env python3
"""Stacked field layout for image-generation dialogs (labels above controls)."""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Tuple

from PySide6.QtCore import QEvent, QObject, QTimer, Qt, QSize
from PySide6.QtGui import QEnterEvent, QIcon, QTextBlock, QTextCursor, QTextLayout, QTextOption
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)
from theme.spin_box import StepSpinBox

from theme.theme_base import asset_path
from theme.theme_service import get_active_theme

IMAGE_GEN_FIELD_RESET_BTN_SIZE = 26
_IMAGE_GEN_TRASH_ICON_PX = 16
IMAGE_GEN_PROMPT_CLEAR_BTN_SCALE = 0.8
IMAGE_GEN_PROMPT_CLEAR_BTN_SIZE = round(
    IMAGE_GEN_FIELD_RESET_BTN_SIZE * IMAGE_GEN_PROMPT_CLEAR_BTN_SCALE
)
_IMAGE_GEN_PROMPT_CLEAR_ICON_PX = round(
    _IMAGE_GEN_TRASH_ICON_PX * IMAGE_GEN_PROMPT_CLEAR_BTN_SCALE
)
IMAGE_GEN_DIM_HELPER_BTN_SIZE = 20 #DGN: 26

IMAGE_GEN_FIELD_GROUP_SPACING = 10
IMAGE_GEN_FIELD_LABEL_SPACING = 2
IMAGE_GEN_FIELD_INSET_H = 12
IMAGE_GEN_FIELD_INSET_V = 8
# Tighter insets for panels embedded in ImageGenUnifiedDialog.
IMAGE_GEN_FIELD_INSET_H_COMPACT = 4
IMAGE_GEN_FIELD_INSET_V_COMPACT = 2
IMAGE_GEN_FIELD_CONTROL_INDENT = 30
# Outer fields kept across ``ImageGenFieldsPanel.clear`` (Model, LoRA, ...).
IMAGE_GEN_PERSISTENT_OUTER_FIELD_COUNT = 2
# Extra right inset so scroll clipping does not cut off control borders / focus rings.
IMAGE_GEN_FIELD_BORDER_PAD = 4
IMAGE_GEN_PROMPT_STYLE_PADDING_V = 10  # 5px top + 5px bottom in dialog stylesheet
IMAGE_GEN_PROMPT_STYLE_BORDER_V = 2  # 1px top + 1px bottom border
IMAGE_GEN_SEED_SPIN_MAX_WIDTH = 118
IMAGE_GEN_PROMPT_MIN_LINE_COUNT = 4
IMAGE_GEN_PROMPT_MAX_LINE_COUNT = 22


def _image_gen_prompt_edit_is_alive(edit: QPlainTextEdit) -> bool:
    from shiboken6 import isValid

    return isValid(edit)


def image_gen_prompt_height_for_lines(line_count: int, font_metrics) -> int:
    """Height for QPlainTextEdit prompt fields (text + padding + border)."""
    lines = max(1, int(line_count))
    line_spacing = font_metrics.lineSpacing()
    return (
        line_spacing * lines
        + line_spacing // 2  # half-line fudge; layout count is slightly conservative
        + IMAGE_GEN_PROMPT_STYLE_PADDING_V
        + IMAGE_GEN_PROMPT_STYLE_BORDER_V
        + 2
    )


def _image_gen_prompt_text_width(edit: QPlainTextEdit) -> int:
    """Usable wrap width; viewport can be 0 before first layout."""
    viewport_w = edit.viewport().width()
    if viewport_w > 1:
        return viewport_w
    frame = edit.frameWidth() * 2
    margins = edit.contentsMargins().left() + edit.contentsMargins().right()
    return max(1, edit.width() - frame - margins - 16)


def _image_gen_prompt_block_line_count(block: QTextBlock, text_width: int) -> int:
    """Layout one document block at text_width and count wrapped lines."""
    layout = QTextLayout(block.text(), block.charFormat().font())
    option = QTextOption()
    option.setWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
    layout.setTextOption(option)
    layout.beginLayout()
    line_count = 0
    while True:
        line = layout.createLine()
        if not line.isValid():
            break
        line.setLineWidth(text_width)
        line_count += 1
    layout.endLayout()
    return max(1, line_count)


def image_gen_prompt_content_line_count(edit: QPlainTextEdit) -> int:
    """Wrapped line count for prompt content.

    QPlainTextEdit block.layout().lineCount() is always 0; lay out each block
    with QTextLayout at the current wrap width instead.
    """
    if not _image_gen_prompt_edit_is_alive(edit):
        return IMAGE_GEN_PROMPT_MIN_LINE_COUNT
    doc = edit.document()
    text_width = _image_gen_prompt_text_width(edit)
    doc.setTextWidth(text_width)

    total_lines = 0
    block = doc.firstBlock()
    while block.isValid():
        total_lines += _image_gen_prompt_block_line_count(block, text_width)
        block = block.next()
    return max(1, total_lines)


def _image_gen_apply_prompt_edit_height(
    edit: QPlainTextEdit,
    min_lines: int,
    max_lines: int,
) -> None:
    if not _image_gen_prompt_edit_is_alive(edit):
        return
    lines = image_gen_prompt_content_line_count(edit)
    lines = max(min_lines, min(lines, max_lines))
    height = image_gen_prompt_height_for_lines(lines, edit.fontMetrics())
    if edit.height() == height:
        return
    edit.setFixedHeight(height)
    edit.updateGeometry()
    widget = edit.parentWidget()
    while widget is not None:
        widget.updateGeometry()
        lay = widget.layout()
        if lay is not None:
            lay.invalidate()
        widget = widget.parentWidget()


_IMAGE_GEN_PROMPT_STREAM_SCROLL_ATTR = "_image_gen_prompt_stream_scroll"


class _ImageGenPromptStreamScrollHelper(QObject):
    """Preserve or follow vertical scroll while AI streams into a prompt field."""

    def __init__(self, edit: QPlainTextEdit) -> None:
        super().__init__(edit)
        self._edit = edit
        self._scrollbar = edit.verticalScrollBar()
        self._streaming_active = False
        self._user_scrolled = False
        self._programmatic_scroll = False
        self._expected_scroll_value = 0
        self._last_text = ""
        self._pending_scroll_value: int | None = None
        self._scrollbar.valueChanged.connect(self._on_scroll_value_changed)

    def _on_scroll_value_changed(self, value: int) -> None:
        if not self._streaming_active or self._programmatic_scroll:
            return
        if value != self._expected_scroll_value:
            self._user_scrolled = True
            self._expected_scroll_value = value

    def begin_streaming(self) -> None:
        self._streaming_active = True
        self._user_scrolled = False
        self._programmatic_scroll = False
        self._last_text = self._edit.toPlainText()
        self._expected_scroll_value = self._scrollbar.value()
        self._pending_scroll_value = None

    def end_streaming(self) -> None:
        self._streaming_active = False
        self._user_scrolled = False
        self._programmatic_scroll = False
        self._last_text = ""
        self._pending_scroll_value = None

    def _apply_scroll_value(self, value: int) -> None:
        sb = self._scrollbar
        clamped = min(max(0, value), sb.maximum())
        self._programmatic_scroll = True
        try:
            sb.setValue(clamped)
            self._expected_scroll_value = clamped
        finally:
            self._programmatic_scroll = False

    def _defer_scroll_value(self, value: int) -> None:
        self._pending_scroll_value = value

        def _apply() -> None:
            if not _image_gen_prompt_edit_is_alive(self._edit):
                return
            if not self._streaming_active:
                return
            if self._pending_scroll_value is None:
                return
            self._apply_scroll_value(self._pending_scroll_value)
            self._pending_scroll_value = None

        QTimer.singleShot(0, _apply)

    def _append_plain_text(self, delta: str) -> None:
        if not delta:
            return
        edit = self._edit
        sb = self._scrollbar
        preserved = sb.value() if self._user_scrolled else None
        self._programmatic_scroll = True
        try:
            cursor = edit.textCursor()
            cursor.movePosition(QTextCursor.MoveOperation.End)
            cursor.insertText(delta)
            if self._user_scrolled and preserved is not None:
                self._apply_scroll_value(preserved)
                self._defer_scroll_value(preserved)
            else:
                self._apply_scroll_value(sb.maximum())
                self._defer_scroll_value(sb.maximum())
        finally:
            self._programmatic_scroll = False

    def _replace_plain_text(self, text: str) -> None:
        edit = self._edit
        sb = self._scrollbar
        preserved = sb.value() if self._user_scrolled else None
        self._programmatic_scroll = True
        try:
            cursor = edit.textCursor()
            cursor.beginEditBlock()
            cursor.select(QTextCursor.SelectionType.Document)
            cursor.insertText(text)
            cursor.endEditBlock()
            if self._user_scrolled and preserved is not None:
                self._apply_scroll_value(preserved)
                self._defer_scroll_value(preserved)
            else:
                self._apply_scroll_value(sb.maximum())
                self._defer_scroll_value(sb.maximum())
        finally:
            self._programmatic_scroll = False

    def set_plain_text(self, text: str) -> None:
        edit = self._edit
        if not _image_gen_prompt_edit_is_alive(edit):
            return
        old_text = self._last_text
        if text.startswith(old_text) and len(text) >= len(old_text):
            delta = text[len(old_text) :]
            if delta:
                self._append_plain_text(delta)
        else:
            self._replace_plain_text(text)
        self._last_text = text


def _image_gen_prompt_stream_scroll_helper(
    edit: QPlainTextEdit,
) -> _ImageGenPromptStreamScrollHelper:
    helper = getattr(edit, _IMAGE_GEN_PROMPT_STREAM_SCROLL_ATTR, None)
    if helper is None:
        helper = _ImageGenPromptStreamScrollHelper(edit)
        setattr(edit, _IMAGE_GEN_PROMPT_STREAM_SCROLL_ATTR, helper)
    return helper


def image_gen_prompt_stream_session_begin(edit: QPlainTextEdit) -> None:
    if not _image_gen_prompt_edit_is_alive(edit):
        return
    _image_gen_prompt_stream_scroll_helper(edit).begin_streaming()


def image_gen_prompt_stream_session_end(edit: QPlainTextEdit) -> None:
    if not _image_gen_prompt_edit_is_alive(edit):
        return
    _image_gen_prompt_stream_scroll_helper(edit).end_streaming()


def image_gen_prompt_edit_set_plain_text(
    edit: QPlainTextEdit,
    text: str,
    *,
    streaming: bool = False,
) -> None:
    """Set prompt text; during streaming, follow new tokens unless user scrolled."""
    if not _image_gen_prompt_edit_is_alive(edit):
        return
    if streaming:
        _image_gen_prompt_stream_scroll_helper(edit).set_plain_text(text)
    else:
        edit.setPlainText(text)


class ImageGenPromptPlainTextEdit(QPlainTextEdit):
    """Prompt field that grows with content between min and max line heights."""

    def __init__(
        self,
        parent: Optional[QWidget] = None,
        *,
        min_lines: int = IMAGE_GEN_PROMPT_MIN_LINE_COUNT,
        max_lines: int = IMAGE_GEN_PROMPT_MAX_LINE_COUNT,
    ):
        super().__init__(parent)
        self._min_lines = max(1, int(min_lines))
        self._max_lines = max(self._min_lines, int(max_lines))
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum
        )
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.document().contentsChanged.connect(self._update_height)
        self._image_gen_updating_height = False
        self._update_height()

    def set_line_limits(
        self,
        min_lines: int = IMAGE_GEN_PROMPT_MIN_LINE_COUNT,
        max_lines: int = IMAGE_GEN_PROMPT_MAX_LINE_COUNT,
    ) -> None:
        self._min_lines = max(1, int(min_lines))
        self._max_lines = max(self._min_lines, int(max_lines))
        self._update_height()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        QTimer.singleShot(0, self._update_height)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._update_height()

    def _update_height(self) -> None:
        if not _image_gen_prompt_edit_is_alive(self):
            return
        if self._image_gen_updating_height:
            return
        self._image_gen_updating_height = True
        try:
            lines = image_gen_prompt_content_line_count(self)
            at_max = lines >= self._max_lines
            policy = (
                Qt.ScrollBarPolicy.ScrollBarAsNeeded
                if at_max
                else Qt.ScrollBarPolicy.ScrollBarAlwaysOff
            )
            if self.verticalScrollBarPolicy() != policy:
                self.setVerticalScrollBarPolicy(policy)
            _image_gen_apply_prompt_edit_height(
                self, self._min_lines, self._max_lines
            )
        finally:
            self._image_gen_updating_height = False


def create_image_gen_prompt_edit(
    parent: Optional[QWidget] = None,
    *,
    min_lines: int = IMAGE_GEN_PROMPT_MIN_LINE_COUNT,
    max_lines: int = IMAGE_GEN_PROMPT_MAX_LINE_COUNT,
) -> ImageGenPromptPlainTextEdit:
    return ImageGenPromptPlainTextEdit(
        parent, min_lines=min_lines, max_lines=max_lines
    )


_IMAGE_GEN_PROMPT_AUTO_HEIGHT_ATTR = "_image_gen_prompt_auto_height"


def _attach_image_gen_prompt_auto_height(
    edit: QPlainTextEdit,
    min_lines: int,
    max_lines: int,
) -> None:
    edit.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
    edit._image_gen_prompt_min_lines = max(1, int(min_lines))  # type: ignore[attr-defined]
    edit._image_gen_prompt_max_lines = max(  # type: ignore[attr-defined]
        edit._image_gen_prompt_min_lines,
        int(max_lines),
    )

    def _apply_height() -> None:
        if not _image_gen_prompt_edit_is_alive(edit):
            return
        if getattr(edit, "_image_gen_updating_height", False):
            return
        edit._image_gen_updating_height = True  # type: ignore[attr-defined]
        try:
            max_lines = edit._image_gen_prompt_max_lines  # type: ignore[attr-defined]
            at_max = image_gen_prompt_content_line_count(edit) >= max_lines
            policy = (
                Qt.ScrollBarPolicy.ScrollBarAsNeeded
                if at_max
                else Qt.ScrollBarPolicy.ScrollBarAlwaysOff
            )
            if edit.verticalScrollBarPolicy() != policy:
                edit.setVerticalScrollBarPolicy(policy)
            _image_gen_apply_prompt_edit_height(
                edit,
                edit._image_gen_prompt_min_lines,  # type: ignore[attr-defined]
                max_lines,
            )
        finally:
            edit._image_gen_updating_height = False  # type: ignore[attr-defined]

    if not getattr(edit, _IMAGE_GEN_PROMPT_AUTO_HEIGHT_ATTR, False):
        setattr(edit, _IMAGE_GEN_PROMPT_AUTO_HEIGHT_ATTR, True)
        edit.document().contentsChanged.connect(_apply_height)

        class _PromptResizeFilter(QObject):
            def eventFilter(self, obj, event) -> bool:
                if event.type() == QEvent.Type.Resize:
                    _apply_height()
                return super().eventFilter(obj, event)

        filt = _PromptResizeFilter(edit)
        edit.installEventFilter(filt)
        edit._image_gen_prompt_resize_filter = filt  # type: ignore[attr-defined]

    _apply_height()


def configure_image_gen_prompt_edit(
    edit: QPlainTextEdit,
    *,
    min_lines: int = IMAGE_GEN_PROMPT_MIN_LINE_COUNT,
    max_lines: int = IMAGE_GEN_PROMPT_MAX_LINE_COUNT,
) -> None:
    """Grow prompt editor with content between min_lines and max_lines."""
    if isinstance(edit, ImageGenPromptPlainTextEdit):
        edit.set_line_limits(min_lines, max_lines)
        return
    _attach_image_gen_prompt_auto_height(edit, min_lines, max_lines)


def wrap_image_gen_bordered_field(
    control: QWidget,
    *,
    bottom_pad: Optional[int] = None,
) -> QWidget:
    """Wrap a bordered control so layout does not clip its bottom/right edges."""
    host = QWidget()
    lay = QVBoxLayout(host)
    lay.setContentsMargins(
        0,
        0,
        0,
        IMAGE_GEN_FIELD_BORDER_PAD if bottom_pad is None else bottom_pad,
    )
    lay.setSpacing(0)
    lay.addWidget(control)
    host.setSizePolicy(
        QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum
    )
    return host


def wrap_image_gen_prompt_subsection(
    control: QWidget,
    parent: Optional[QWidget] = None,
) -> QWidget:
    """Indent for blocks under the image prompt (import row, system prompt section)."""
    outer = QWidget(parent)
    outer_lay = QHBoxLayout(outer)
    outer_lay.setContentsMargins(IMAGE_GEN_FIELD_CONTROL_INDENT, 0, 0, 0)
    outer_lay.setSpacing(0)
    inner = QWidget(outer)
    inner_lay = QVBoxLayout(inner)
    inner_lay.setContentsMargins(
        IMAGE_GEN_FIELD_BORDER_PAD, 0, IMAGE_GEN_FIELD_BORDER_PAD, 0
    )
    inner_lay.setSpacing(0)
    inner_lay.addWidget(control)
    hp = control.sizePolicy().horizontalPolicy()
    vp = control.sizePolicy().verticalPolicy()
    if hp == QSizePolicy.Policy.Expanding:
        outer_lay.addWidget(inner, 1)
        outer.setSizePolicy(QSizePolicy.Policy.Expanding, vp)
    else:
        outer_lay.addWidget(inner, 0, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        outer.setSizePolicy(QSizePolicy.Policy.Maximum, vp)
    return outer


IMAGE_GEN_PROMPT_BUTTON_BAR_SPACING = 16


def create_image_gen_prompt_button_bar_row(
    parent: Optional[QWidget] = None,
    *,
    horizontal_pad: bool = True,
) -> tuple[QWidget, QHBoxLayout]:
    """Horizontal button/checkbox row under a prompt field (import or Gen Prompt)."""
    row = QWidget(parent)
    row.setObjectName("imageGenPromptButtonBarRow")
    row.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
    layout = QHBoxLayout(row)
    pad = IMAGE_GEN_FIELD_BORDER_PAD if horizontal_pad else 0
    layout.setContentsMargins(pad, 0, pad, 0)
    layout.setSpacing(IMAGE_GEN_PROMPT_BUTTON_BAR_SPACING)
    layout.setAlignment(
        Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
    )
    return row, layout


IMAGE_GEN_CHECKBOX_ROW_SPACING = 14
IMAGE_GEN_COLUMN_ROW_SPACING = 10
IMAGE_GEN_BELOW_PROMPT_SPACING = 8
IMAGE_GEN_SLIDER_TRACK_WIDTH = 200
IMAGE_GEN_SLIDER_ROW_SPACING = 8
IMAGE_GEN_FIELD_LABEL_OBJECT_NAME = "imageGenFieldLabel"
IMAGE_GEN_FIELD_LABEL_FONT_SIZE = 14
# Two-column flow below the prompt when there are enough fields and width.
IMAGE_GEN_TWO_COLUMN_MIN_FIELD_COUNT = 5
IMAGE_GEN_TWO_COLUMN_MIN_ITEM_WIDTH = (
    IMAGE_GEN_FIELD_CONTROL_INDENT
    + IMAGE_GEN_SLIDER_TRACK_WIDTH
    + IMAGE_GEN_SLIDER_ROW_SPACING
    + 80
    + IMAGE_GEN_SLIDER_ROW_SPACING
    + IMAGE_GEN_FIELD_RESET_BTN_SIZE
)
IMAGE_GEN_TWO_COLUMN_MIN_WIDTH = (
    IMAGE_GEN_TWO_COLUMN_MIN_ITEM_WIDTH * 2 + IMAGE_GEN_COLUMN_ROW_SPACING
)
IMAGE_GEN_HALF_COLUMN_ITEM_WIDTH = (
    IMAGE_GEN_TWO_COLUMN_MIN_ITEM_WIDTH - IMAGE_GEN_COLUMN_ROW_SPACING
) // 2
_IMAGE_GEN_HALF_COLUMN_CONTROL_OVERHEAD = (
    IMAGE_GEN_SLIDER_ROW_SPACING
    + 72
    + IMAGE_GEN_SLIDER_ROW_SPACING
    + IMAGE_GEN_FIELD_RESET_BTN_SIZE
)
IMAGE_GEN_HALF_COLUMN_SLIDER_TRACK_WIDTH = max(
    40,
    IMAGE_GEN_HALF_COLUMN_ITEM_WIDTH - _IMAGE_GEN_HALF_COLUMN_CONTROL_OVERHEAD,
)


class _ImageGenFieldsReflowFilter(QObject):
    def __init__(self, panel: "ImageGenFieldsPanel") -> None:
        super().__init__(panel.widget)
        self._panel = panel

    def eventFilter(self, obj, event) -> bool:
        if event.type() == QEvent.Type.Resize:
            panel = self._panel
            width = panel._available_controls_width()
            if width > 0:
                two_col = panel._use_two_column_layout(len(panel._control_groups))
                if (
                    width != panel._last_reflow_width
                    or two_col != panel._last_reflow_two_col
                ):
                    panel._last_reflow_width = width
                    panel._last_reflow_two_col = two_col
                    panel._schedule_reflow()
        return super().eventFilter(obj, event)


def configure_image_gen_slider_track(
    slider: QWidget, *, track_width: Optional[int] = None
) -> None:
    """Fixed-width slider track; value widget sits beside it on the left."""
    width = (
        track_width if track_width is not None else IMAGE_GEN_SLIDER_TRACK_WIDTH
    )
    slider.setFixedWidth(width)
    slider.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)


def configure_image_gen_int_slider_spin(spin: StepSpinBox) -> None:
    """Fixed-width spin sized for six digit characters."""
    spin.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
    spin.setFixedWidth(spin.char_width())


def image_gen_field_reset_trash_stylesheet(
    *,
    selector: str = "QPushButton",
) -> str:
    """Small trash icon button for resetting a field to its plugin default."""
    from imagegen_plugins.image_gen_dialog import image_gen_preview_client_background_hex

    t = get_active_theme()
    chrome_bg = image_gen_preview_client_background_hex()
    sz = IMAGE_GEN_FIELD_RESET_BTN_SIZE
    return f"""
        {selector} {{
            background-color: {chrome_bg};
            border: 1px solid {t.border_default_hex};
            border-radius: 3px;
            padding: 0px;
            min-width: {sz}px;
            max-width: {sz}px;
            min-height: {sz}px;
            max-height: {sz}px;
        }}
        {selector}[resetActive="false"] {{
            opacity: 0.35;
        }}
        {selector}:focus {{
            border: 1px solid {t.current_image_border_color_hex};
            outline: none;
        }}
        {selector}:hover {{
            background-color: {t.tab_button_hover_bg_hex};
            border: 1px solid {t.tab_button_hover_bg_hex};
        }}
        {selector}:pressed {{
            background-color: {t.sidebar_splitter_handle_hex};
        }}
    """


def sync_image_gen_field_reset_button_active(
    button: QPushButton, *, active: bool
) -> None:
    """Keep reset buttons hoverable; dim when already at the plugin default."""
    button.setProperty("resetActive", "true" if active else "false")
    button.setEnabled(True)
    style = button.style()
    if style is not None:
        style.unpolish(button)
        style.polish(button)
    button.update()


class _ImageGenFieldResetButton(QPushButton):
    """Trash reset control with reliable hover icon swap (works when inactive)."""

    def __init__(
        self, parent: Optional[QWidget] = None, *, tooltip: str = "Reset to default"
    ) -> None:
        super().__init__("", parent)
        self.setObjectName("imageGenFieldResetBtn")
        self.setToolTip(tooltip)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._normal_icon = QIcon(asset_path("trash_icon.png"))
        self._hover_icon = QIcon(asset_path("trash_icon_hover.png"))
        self._hovered = False
        self._apply_icon()
        self.setStyleSheet(
            image_gen_field_reset_trash_stylesheet(selector="QPushButton")
        )
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.setFixedSize(
            IMAGE_GEN_FIELD_RESET_BTN_SIZE, IMAGE_GEN_FIELD_RESET_BTN_SIZE
        )
        sync_image_gen_field_reset_button_active(self, active=False)

    def _apply_icon(self) -> None:
        icon = self._hover_icon if self._hovered else self._normal_icon
        px = _IMAGE_GEN_TRASH_ICON_PX
        self.setIcon(icon)
        self.setIconSize(QSize(px, px))

    def enterEvent(self, event: QEnterEvent) -> None:
        self._hovered = True
        self._apply_icon()
        super().enterEvent(event)

    def leaveEvent(self, event: QEvent) -> None:
        self._hovered = False
        self._apply_icon()
        super().leaveEvent(event)


def image_gen_field_reset_btn_dialog_stylesheet() -> str:
    """Dialog-scoped rules so app-wide QPushButton min-width does not hide reset icons."""
    return image_gen_field_reset_trash_stylesheet(
        selector="#imageGenDialog QPushButton#imageGenFieldResetBtn"
    )


def image_gen_prompt_copy_btn_stylesheet(
    *,
    selector: str = "QPushButton",
) -> str:
    """Small copy button for prompt text fields."""
    from imagegen_plugins.image_gen_dialog import image_gen_preview_client_background_hex

    t = get_active_theme()
    chrome_bg = image_gen_preview_client_background_hex()
    sz = IMAGE_GEN_FIELD_RESET_BTN_SIZE
    return f"""
        {selector} {{
            background-color: {chrome_bg};
            border: 1px solid {t.border_default_hex};
            border-radius: 3px;
            padding: 0px;
            min-width: {sz}px;
            max-width: {sz}px;
            min-height: {sz}px;
            max-height: {sz}px;
            color: {t.text_disabled_hex};
        }}
        {selector}:focus {{
            border: 1px solid {t.current_image_border_color_hex};
            outline: none;
        }}
        {selector}:hover {{
            background-color: {t.tab_button_hover_bg_hex};
            border: 1px solid {t.tab_button_hover_bg_hex};
            color: {t.button_text_hover_hex};
        }}
        {selector}:pressed {{
            background-color: {t.sidebar_splitter_handle_hex};
        }}
        {selector}:disabled {{
            opacity: 0.35;
        }}
    """


def image_gen_prompt_copy_btn_dialog_stylesheet() -> str:
    return image_gen_prompt_copy_btn_stylesheet(
        selector="#imageGenDialog QPushButton#imageGenPromptCopyBtn"
    )


def image_gen_prompt_clear_btn_stylesheet(
    *,
    selector: str = "QPushButton",
) -> str:
    """Small clear (X) button beside the image prompt label."""
    from imagegen_plugins.image_gen_dialog import image_gen_preview_client_background_hex

    t = get_active_theme()
    chrome_bg = image_gen_preview_client_background_hex()
    sz = IMAGE_GEN_PROMPT_CLEAR_BTN_SIZE
    return f"""
        {selector} {{
            background-color: {chrome_bg};
            border: 1px solid {t.border_default_hex};
            border-radius: 3px;
            padding: 0px;
            min-width: {sz}px;
            max-width: {sz}px;
            min-height: {sz}px;
            max-height: {sz}px;
        }}
        {selector}:focus {{
            border: 1px solid {t.current_image_border_color_hex};
            outline: none;
        }}
        {selector}:hover {{
            background-color: {t.tab_button_hover_bg_hex};
            border: 1px solid {t.tab_button_hover_bg_hex};
        }}
        {selector}:pressed {{
            background-color: {t.sidebar_splitter_handle_hex};
        }}
        {selector}:disabled {{
            opacity: 0.35;
        }}
    """


def image_gen_prompt_clear_btn_dialog_stylesheet() -> str:
    return image_gen_prompt_clear_btn_stylesheet(
        selector="#imageGenDialog QPushButton#imageGenPromptClearBtn"
    )


def image_gen_system_prompt_copy_btn_dialog_stylesheet() -> str:
    return image_gen_prompt_copy_btn_stylesheet(
        selector="#imageGenDialog QPushButton#imageGenSystemPromptCopyBtn"
    )


def image_gen_system_prompt_clear_btn_dialog_stylesheet() -> str:
    return image_gen_prompt_clear_btn_stylesheet(
        selector="#imageGenDialog QPushButton#imageGenSystemPromptClearBtn"
    )


def image_gen_system_prompt_voice_mic_btn_dialog_stylesheet() -> str:
    return image_gen_prompt_voice_mic_btn_stylesheet(
        selector="#imageGenDialog QPushButton#imageGenSystemPromptVoiceMicBtn"
    )


class _ImageGenPromptClearButton(QPushButton):
    """Boxed clear icon for the image prompt field label row."""

    def __init__(
        self,
        edit: QPlainTextEdit,
        parent: Optional[QWidget] = None,
        *,
        object_name: str = "imageGenPromptClearBtn",
    ) -> None:
        super().__init__("", parent)
        self._edit = edit
        self.setObjectName(object_name)
        self.setToolTip("Clear prompt")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._normal_icon = QIcon(asset_path("trash_icon.png"))
        self._hover_icon = QIcon(asset_path("trash_icon_hover.png"))
        self._apply_icon()
        clear_selector = (
            f"QPushButton#{object_name}"
            if object_name
            else "QPushButton"
        )
        self.setStyleSheet(
            image_gen_prompt_clear_btn_stylesheet(selector=clear_selector)
        )
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.setFixedSize(
            IMAGE_GEN_PROMPT_CLEAR_BTN_SIZE, IMAGE_GEN_PROMPT_CLEAR_BTN_SIZE
        )
        self.clicked.connect(self._clear_prompt)

    def _apply_icon(self) -> None:
        px = _IMAGE_GEN_PROMPT_CLEAR_ICON_PX
        self.setIcon(self._normal_icon)
        self.setIconSize(QSize(px, px))

    def _clear_prompt(self) -> None:
        self._edit.setPlainText("")
        self._edit.setFocus()


def create_image_gen_prompt_clear_button(
    edit: QPlainTextEdit,
    parent: Optional[QWidget] = None,
    *,
    object_name: str = "imageGenPromptClearBtn",
) -> QPushButton:
    return _ImageGenPromptClearButton(edit, parent, object_name=object_name)


def make_image_gen_prompt_label_row(
    label_text: str,
    edit: QPlainTextEdit,
    parent: Optional[QWidget] = None,
    *,
    label_row_object_name: str = "imageGenPromptLabelRow",
    clear_object_name: str = "imageGenPromptClearBtn",
) -> QWidget:
    """Field heading with a clear button to the right of the label."""
    row = QWidget(parent)
    row.setObjectName(label_row_object_name)
    row.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    layout = QHBoxLayout(row)
    layout.setContentsMargins(0, 8, 0, 0)
    layout.setSpacing(6)
    layout.addWidget(make_image_gen_field_label(label_text, row), 0)
    layout.addWidget(
        create_image_gen_prompt_clear_button(
            edit, row, object_name=clear_object_name
        ),
        0,
        Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
    )
    layout.addStretch(1)
    return row


def image_gen_prompt_voice_mic_btn_stylesheet(
    *,
    selector: str = "QPushButton",
) -> str:
    """Small mic button for prompt text fields (icon set on the widget)."""
    from imagegen_plugins.image_gen_dialog import image_gen_preview_client_background_hex

    t = get_active_theme()
    chrome_bg = image_gen_preview_client_background_hex()
    sz = IMAGE_GEN_FIELD_RESET_BTN_SIZE
    return f"""
        {selector} {{
            background-color: {chrome_bg};
            border: 1px solid {t.border_default_hex};
            border-radius: 3px;
            padding: 0px;
            min-width: {sz}px;
            max-width: {sz}px;
            min-height: {sz}px;
            max-height: {sz}px;
        }}
        {selector}:focus {{
            border: 1px solid {t.current_image_border_color_hex};
            outline: none;
        }}
        {selector}:hover {{
            background-color: {t.tab_button_hover_bg_hex};
            border: 1px solid {t.tab_button_hover_bg_hex};
        }}
        {selector}:pressed {{
            background-color: {t.sidebar_splitter_handle_hex};
        }}
        {selector}:disabled {{
            opacity: 0.35;
        }}
    """


def image_gen_prompt_voice_mic_btn_dialog_stylesheet() -> str:
    return image_gen_prompt_voice_mic_btn_stylesheet(
        selector="#imageGenDialog QPushButton#imageGenPromptVoiceMicBtn"
    )


def create_image_gen_prompt_voice_mic_button(
    edit: QPlainTextEdit,
    parent: Optional[QWidget] = None,
    *,
    object_name: str = "imageGenPromptVoiceMicBtn",
) -> Optional[QPushButton]:
    try:
        from bundle_capabilities import voice_input_ui_enabled

        if not voice_input_ui_enabled():
            return None
    except ImportError:
        pass
    try:
        from whisper_voice_input import create_sidebar_voice_mic_button
    except ImportError:
        return None

    btn = create_sidebar_voice_mic_button(
        edit, parent, size=IMAGE_GEN_FIELD_RESET_BTN_SIZE
    )
    if btn is None:
        return None
    btn.setObjectName(object_name)
    btn.setStyleSheet(
        image_gen_prompt_voice_mic_btn_stylesheet(
            selector=f"QPushButton#{object_name}"
        )
    )
    btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
    return btn


def create_image_gen_prompt_copy_button(
    edit: QPlainTextEdit,
    parent: Optional[QWidget] = None,
    *,
    object_name: str = "imageGenPromptCopyBtn",
) -> QPushButton:
    from thumbnails.thumbnail_constants import COPY_SYMBOL

    btn = QPushButton(COPY_SYMBOL, parent)
    btn.setObjectName(object_name)
    btn.setToolTip("Copy to clipboard")
    btn.setCursor(Qt.CursorShape.PointingHandCursor)
    btn.setStyleSheet(
        image_gen_prompt_copy_btn_stylesheet(
            selector=f"QPushButton#{object_name}"
        )
    )
    btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
    btn.setFixedSize(IMAGE_GEN_FIELD_RESET_BTN_SIZE, IMAGE_GEN_FIELD_RESET_BTN_SIZE)

    def _copy_prompt() -> None:
        from copy_feedback import copy_text_to_clipboard

        copy_text_to_clipboard(edit.toPlainText(), anchor=edit)

    btn.clicked.connect(_copy_prompt)
    return btn


def build_image_gen_prompt_field_action_column(
    edit: QPlainTextEdit,
    parent: QWidget,
    *,
    copy_object_name: str = "imageGenPromptCopyBtn",
    mic_object_name: str = "imageGenPromptVoiceMicBtn",
    action_column_object_name: str = "imageGenPromptActionCol",
) -> tuple[QWidget, QVBoxLayout, QPushButton, Optional[QPushButton]]:
    """Copy and optional mic buttons stacked to the right of a prompt field."""
    action_col = QWidget(parent)
    action_col.setObjectName(action_column_object_name)
    action_layout = QVBoxLayout(action_col)
    action_layout.setContentsMargins(0, 0, 0, 0)
    action_layout.setSpacing(4)
    copy_btn = create_image_gen_prompt_copy_button(
        edit, action_col, object_name=copy_object_name
    )
    action_layout.addWidget(
        copy_btn,
        0,
        Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter,
    )
    mic_btn = create_image_gen_prompt_voice_mic_button(
        edit, action_col, object_name=mic_object_name
    )
    if mic_btn is not None:
        action_layout.addWidget(
            mic_btn,
            0,
            Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter,
        )
    return action_col, action_layout, copy_btn, mic_btn


def wrap_image_gen_prompt_row_with_copy(
    display_control: QWidget,
    edit: QPlainTextEdit,
    *,
    copy_object_name: str = "imageGenPromptCopyBtn",
    mic_object_name: str = "imageGenPromptVoiceMicBtn",
    action_column_object_name: str = "imageGenPromptActionCol",
) -> QWidget:
    """Prompt editor with copy and optional voice-input buttons to the right."""
    row_w = QWidget()
    row = QHBoxLayout(row_w)
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(4)
    row.addWidget(display_control, 1)
    action_col, _, _, _ = build_image_gen_prompt_field_action_column(
        edit,
        row_w,
        copy_object_name=copy_object_name,
        mic_object_name=mic_object_name,
        action_column_object_name=action_column_object_name,
    )
    row.addWidget(
        action_col,
        0,
        Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignRight,
    )
    row_w.setSizePolicy(
        QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum
    )
    return row_w


def image_gen_dim_helper_icon_stylesheet(
    icon_name: str,
    *,
    hover_icon_name: Optional[str] = None,
    selector: str = "QPushButton",
) -> str:
    """Small square icon button for custom-size dimension helpers."""
    from imagegen_plugins.image_gen_dialog import image_gen_preview_client_background_hex

    t = get_active_theme()
    chrome_bg = image_gen_preview_client_background_hex()
    icon_url = f"url({asset_path(icon_name)})"
    hover_name = hover_icon_name or icon_name.replace(".svg", "_hover.svg").replace(
        ".png", "_hover.png"
    )
    hover_url = f"url({asset_path(hover_name)})"
    sz = IMAGE_GEN_DIM_HELPER_BTN_SIZE
    return f"""
        {selector} {{
            background-color: {chrome_bg};
            border: 1px solid {t.border_default_hex};
            border-radius: 3px;
            padding: 0px;
            min-width: {sz}px;
            max-width: {sz}px;
            min-height: {sz}px;
            max-height: {sz}px;
            image: {icon_url};
        }}
        {selector}:focus {{
            border: 1px solid {t.current_image_border_color_hex};
            outline: none;
        }}
        {selector}:hover {{
            background-color: {t.tab_button_hover_bg_hex};
            border: 1px solid {t.tab_button_hover_bg_hex};
            image: {hover_url};
        }}
        {selector}:pressed {{
            background-color: {t.sidebar_splitter_handle_hex};
        }}
        {selector}:disabled {{
            opacity: 0.35;
        }}
    """


def create_image_gen_dim_helper_icon_button(
    icon_name: str,
    *,
    hover_icon_name: Optional[str] = None,
    tooltip: str = "",
    parent: Optional[QWidget] = None,
) -> QPushButton:
    btn = QPushButton(parent)
    btn.setObjectName("imageGenDimHelperBtn")
    if tooltip:
        btn.setToolTip(tooltip)
    btn.setStyleSheet(
        image_gen_dim_helper_icon_stylesheet(
            icon_name,
            hover_icon_name=hover_icon_name,
            selector="QPushButton#imageGenDimHelperBtn",
        )
    )
    btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
    btn.setFixedSize(IMAGE_GEN_DIM_HELPER_BTN_SIZE, IMAGE_GEN_DIM_HELPER_BTN_SIZE)
    return btn


def create_image_gen_field_reset_button(
    parent: Optional[QWidget] = None,
    *,
    tooltip: str = "Reset to default",
) -> QPushButton:
    return _ImageGenFieldResetButton(parent, tooltip=tooltip)


def wrap_image_gen_slider_row(
    slider: QWidget,
    value_widget: QWidget,
    *,
    reset_button: Optional[QPushButton] = None,
    track_width: Optional[int] = None,
) -> QWidget:
    """Slider + spin/label row aligned left; slider does not stretch with panel width."""
    configure_image_gen_slider_track(slider, track_width=track_width)
    value_widget.setSizePolicy(
        QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed
    )
    row_w = QWidget()
    row = QHBoxLayout(row_w)
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(IMAGE_GEN_SLIDER_ROW_SPACING)
    row.addWidget(slider, 0, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
    row.addWidget(
        value_widget, 0, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
    )
    if reset_button is not None:
        row.addWidget(
            reset_button,
            0,
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
        )
    row_w.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
    return row_w


def wrap_image_gen_choice_row(
    combo: QWidget,
    *,
    reset_button: Optional[QPushButton] = None,
) -> QWidget:
    """Combo box row with optional reset button at the end."""
    if reset_button is None:
        return combo
    row_w = QWidget()
    row = QHBoxLayout(row_w)
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(IMAGE_GEN_SLIDER_ROW_SPACING)
    row.addWidget(combo, 0, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
    row.addWidget(
        reset_button,
        0,
        Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
    )
    row_w.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
    return row_w


def make_image_gen_field_label(text: str, parent: Optional[QWidget] = None) -> QLabel:
    label = QLabel(text, parent)
    label.setObjectName(IMAGE_GEN_FIELD_LABEL_OBJECT_NAME)
    label.setWordWrap(True)
    label.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
    return label


def _build_image_gen_column_cell(
    parent: QWidget,
    label_text: str,
    control: QWidget,
    *,
    half_column: bool = False,
) -> QWidget:
    cell = QWidget(parent)
    cell_layout = QVBoxLayout(cell)
    cell_layout.setContentsMargins(0, 0, 0, 0)
    cell_layout.setSpacing(IMAGE_GEN_FIELD_LABEL_SPACING)
    cell_layout.addWidget(make_image_gen_field_label(label_text, cell), 0)
    if control.sizePolicy().horizontalPolicy() == QSizePolicy.Policy.Maximum:
        cell_layout.addWidget(
            wrap_image_gen_field_control_indent(control, cell),
            0,
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
        )
    else:
        control.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        cell_layout.addWidget(
            wrap_image_gen_field_control_indent(control, cell), 0
        )
    if half_column:
        cell.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    return cell


def build_image_gen_half_column_row(
    slots: List[Optional[Tuple[str, QWidget]]],
    *,
    parent: Optional[QWidget] = None,
) -> QWidget:
    """Two equal half-columns on one line; None slots are blank fillers."""
    row_w = QWidget(parent)
    row = QHBoxLayout(row_w)
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(IMAGE_GEN_COLUMN_ROW_SPACING)
    normalized = (list(slots) + [None, None])[:2]
    for slot in normalized:
        if slot is None:
            filler = QWidget(row_w)
            filler.setSizePolicy(
                QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
            )
            row.addWidget(filler, 1)
        else:
            label_text, control = slot
            row.addWidget(
                _build_image_gen_column_cell(
                    row_w, label_text, control, half_column=True
                ),
                1,
            )
    row_w.setFixedWidth(IMAGE_GEN_TWO_COLUMN_MIN_ITEM_WIDTH)
    row_w.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
    return row_w


def wrap_image_gen_field_control_indent(
    control: QWidget,
    parent: Optional[QWidget] = None,
) -> QWidget:
    """Left inset for controls sitting under a field heading."""
    host = QWidget(parent)
    row = QHBoxLayout(host)
    row.setContentsMargins(IMAGE_GEN_FIELD_CONTROL_INDENT, 0, 0, 0)
    row.setSpacing(0)
    hp = control.sizePolicy().horizontalPolicy()
    vp = control.sizePolicy().verticalPolicy()
    align = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
    if hp == QSizePolicy.Policy.Expanding:
        row.addWidget(control, 1)
        host.setSizePolicy(QSizePolicy.Policy.Expanding, vp)
    else:
        row.addWidget(control, 0, align)
        host.setSizePolicy(QSizePolicy.Policy.Maximum, vp)
    return host


class ImageGenFieldsPanel:
    """Vertical form: model + full-width prompt, then controls with optional side buttons."""

    def __init__(self, parent: QWidget, *, compact: bool = False):
        self.widget = QWidget(parent)
        self._layout = QVBoxLayout(self.widget)
        if compact:
            inset_h = IMAGE_GEN_FIELD_INSET_H_COMPACT
            inset_v = IMAGE_GEN_FIELD_INSET_V_COMPACT
        else:
            inset_h = IMAGE_GEN_FIELD_INSET_H
            inset_v = IMAGE_GEN_FIELD_INSET_V
        self._inset_h = inset_h
        self._inset_right = inset_h + IMAGE_GEN_FIELD_BORDER_PAD
        self._layout.setContentsMargins(
            inset_h,
            inset_v,
            self._inset_right,
            inset_v,
        )
        self._layout.setSpacing(IMAGE_GEN_FIELD_GROUP_SPACING)
        self._layout.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop
        )

        self._prompt_group: Optional[QWidget] = None
        self._prompt_import_host: Optional[QWidget] = None
        self._below_row = QWidget(self.widget)
        self._below_row.setObjectName("imageGenBelowPromptRow")
        self._below_layout = QHBoxLayout(self._below_row)
        self._below_layout.setContentsMargins(0, 0, 0, 0)
        self._below_layout.setSpacing(IMAGE_GEN_BELOW_PROMPT_SPACING)
        self._below_layout.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop
        )

        self._controls_host = QWidget(self._below_row)
        self._controls_host.setObjectName("imageGenControlsHost")
        self._controls_layout = QVBoxLayout(self._controls_host)
        self._controls_layout.setContentsMargins(0, 0, 0, 0)
        self._controls_layout.setSpacing(IMAGE_GEN_FIELD_GROUP_SPACING)
        self._controls_layout.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop
        )
        self._below_layout.addWidget(self._controls_host, 1)

        self._side_btn_host: Optional[QWidget] = None
        self._below_row_in_layout = False
        self._control_groups: List[QWidget] = []
        self._checkbox_groups: List[QWidget] = []
        self._reflow_timer = QTimer(self.widget)
        self._reflow_timer.setSingleShot(True)
        self._reflow_timer.timeout.connect(self._reflow_controls_layout)
        self._last_reflow_width = -1
        self._last_reflow_two_col: Optional[bool] = None
        self._scroll_area: Optional[QScrollArea] = None
        self._resize_filter = _ImageGenFieldsReflowFilter(self)
        self._controls_host.installEventFilter(self._resize_filter)
        self.widget.installEventFilter(self._resize_filter)
        from imagegen_plugins.image_gen_dialog import apply_image_gen_preview_client_background

        for chrome in (self.widget, self._below_row, self._controls_host):
            apply_image_gen_preview_client_background(chrome)

    def count(self) -> int:
        return (
            self._layout.count()
            + len(self._control_groups)
            + len(self._checkbox_groups)
        )

    def reflow_controls(self) -> None:
        """Recompute single- vs two-column layout for fields below the prompt."""
        self._schedule_reflow()

    def _schedule_reflow(self) -> None:
        self._reflow_timer.start(0)

    def _available_controls_width(self) -> int:
        width = self._controls_host.width()
        if width > 0:
            return width
        return max(
            0,
            self.widget.width() - self._inset_h - self._inset_right,
        )

    def _use_two_column_layout(self, control_count: int) -> bool:
        if control_count < IMAGE_GEN_TWO_COLUMN_MIN_FIELD_COUNT:
            return False
        return self._available_controls_width() >= IMAGE_GEN_TWO_COLUMN_MIN_WIDTH

    def _side_button_width(self) -> int:
        if self._side_btn_host is None or not self._side_btn_host.isVisible():
            return 0
        return (
            self._side_btn_host.sizeHint().width()
            + IMAGE_GEN_BELOW_PROMPT_SPACING
        )

    def _group_natural_width(self, group: QWidget) -> int:
        width = group.sizeHint().width()
        if width <= 0:
            width = group.minimumSizeHint().width()
        return max(0, width)

    def _controls_content_minimum_width(self) -> int:
        groups = self._control_groups + self._checkbox_groups
        if not groups:
            return self._side_button_width()

        if self._use_two_column_layout(len(self._control_groups)):
            base = IMAGE_GEN_TWO_COLUMN_MIN_WIDTH
        else:
            base = 0
            for group in groups:
                base = max(base, self._group_natural_width(group))

        return base + self._side_button_width()

    def _outer_fields_minimum_width(self) -> int:
        outer_min = 0
        for i in range(self._layout.count()):
            item = self._layout.itemAt(i)
            if item is None:
                continue
            widget = item.widget()
            if widget is None or widget is self._below_row:
                continue
            outer_min = max(outer_min, self._group_natural_width(widget))
        return outer_min

    def _content_minimum_width(self) -> int:
        area_min = max(
            self._outer_fields_minimum_width(),
            self._controls_content_minimum_width(),
        )
        return area_min + self._inset_h + self._inset_right

    def _sync_minimum_widths(self) -> None:
        """Stop horizontal shrink once fixed-width controls would need a scrollbar."""
        controls_min = self._controls_content_minimum_width()
        content_min = self._content_minimum_width()

        self._controls_host.setMinimumWidth(controls_min)
        self._below_row.setMinimumWidth(controls_min)
        self.widget.setMinimumWidth(content_min)
        if self._scroll_area is not None:
            self._scroll_area.setMinimumWidth(content_min)
            splitter = self._scroll_area.parent()
            clamp = getattr(splitter, "_clamp_left_size", None)
            if callable(clamp):
                QTimer.singleShot(0, clamp)

    def _detach_below_prompt_groups(self) -> None:
        for group in self._control_groups + self._checkbox_groups:
            group.setParent(None)

    def _clear_controls_layout_wrappers(self) -> None:
        self._detach_below_prompt_groups()
        while self._controls_layout.count():
            item = self._controls_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _mount_group_in_layout(
        self,
        layout: QVBoxLayout,
        group: QWidget,
    ) -> None:
        compact = (
            group.sizePolicy().horizontalPolicy() == QSizePolicy.Policy.Maximum
        )
        if not compact:
            group.setSizePolicy(
                QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
            )
            layout.addWidget(group)
        else:
            layout.addWidget(
                group,
                0,
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop,
            )

    def _make_controls_column(
        self,
        groups: List[QWidget],
        parent: QWidget,
    ) -> QWidget:
        column = QWidget(parent)
        col_layout = QVBoxLayout(column)
        col_layout.setContentsMargins(0, 0, 0, 0)
        col_layout.setSpacing(IMAGE_GEN_FIELD_GROUP_SPACING)
        col_layout.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop
        )
        for group in groups:
            self._mount_group_in_layout(col_layout, group)
        column.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum
        )
        return column

    def _reflow_controls_layout(self) -> None:
        if not self._control_groups and not self._checkbox_groups:
            self._clear_controls_layout_wrappers()
            self._sync_minimum_widths()
            return

        width = self._available_controls_width()
        two_col = self._use_two_column_layout(len(self._control_groups))
        self._last_reflow_width = width
        self._last_reflow_two_col = two_col

        self._ensure_below_row_in_layout()
        self._clear_controls_layout_wrappers()

        controls = list(self._control_groups)
        checkboxes = list(self._checkbox_groups)
        if self._use_two_column_layout(len(controls)):
            first_count = (len(controls) + 1) // 2
            row = QWidget(self._controls_host)
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(IMAGE_GEN_COLUMN_ROW_SPACING)
            row_layout.setAlignment(
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop
            )
            row_layout.addWidget(
                self._make_controls_column(controls[:first_count], row), 1
            )
            row_layout.addWidget(
                self._make_controls_column(controls[first_count:], row), 1
            )
            row.setSizePolicy(
                QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum
            )
            self._controls_layout.addWidget(row)
            if checkboxes:
                checkbox_col = self._make_controls_column(
                    checkboxes, self._controls_host
                )
                self._controls_layout.addWidget(checkbox_col)
        else:
            for group in controls + checkboxes:
                self._mount_group_in_layout(self._controls_layout, group)

        self._sync_minimum_widths()

    def prepend_control_group(self, group: QWidget) -> None:
        self._ensure_below_row_in_layout()
        self._control_groups.insert(0, group)
        self._schedule_reflow()

    def _append_control_group(self, group: QWidget) -> None:
        self._ensure_below_row_in_layout()
        self._control_groups.append(group)
        self._schedule_reflow()

    def _append_checkbox_group(self, group: QWidget) -> None:
        self._ensure_below_row_in_layout()
        self._checkbox_groups.append(group)
        self._schedule_reflow()

    def _ensure_below_row_in_layout(self) -> None:
        if not self._below_row_in_layout:
            self._layout.addWidget(self._below_row)
            self._below_row_in_layout = True

    def attach_side_button_column(self, host: Optional[QWidget]) -> None:
        """Place a vertical button stack to the right of controls (below the prompt)."""
        if host is None:
            if self._side_btn_host is not None:
                self._below_layout.removeWidget(self._side_btn_host)
                self._side_btn_host.hide()
                self._side_btn_host = None
                self._schedule_reflow()
            return
        self._ensure_below_row_in_layout()
        if self._side_btn_host is not None and self._side_btn_host is not host:
            self._below_layout.removeWidget(self._side_btn_host)
        self._side_btn_host = host
        host.show()
        if self._below_layout.indexOf(host) < 0:
            self._below_layout.addWidget(
                host, 0, Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignRight
            )
        self._schedule_reflow()

    def clear(self, *, keep: int = 0) -> None:
        if self._prompt_group is not None:
            self._layout.removeWidget(self._prompt_group)
            self._prompt_group.deleteLater()
            self._prompt_group = None
        self._prompt_import_host = None

        for group in self._control_groups + self._checkbox_groups:
            group.deleteLater()
        self._control_groups.clear()
        self._checkbox_groups.clear()
        self._clear_controls_layout_wrappers()

        if self._side_btn_host is not None:
            self._below_layout.removeWidget(self._side_btn_host)
            self._side_btn_host.hide()

        if self._below_row_in_layout:
            self._layout.removeWidget(self._below_row)
            self._below_row_in_layout = False

        self._controls_host.setMinimumWidth(0)
        self._below_row.setMinimumWidth(0)
        self.widget.setMinimumWidth(0)
        if self._scroll_area is not None:
            self._scroll_area.setMinimumWidth(0)

        while self._layout.count() > keep:
            item = self._layout.takeAt(keep)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def add_group(self, group: QWidget) -> None:
        self._append_control_group(group)

    def add_prompt_field(
        self,
        label_text: str,
        control: QWidget,
    ) -> None:
        """Full-width prompt editor above the controls / side-button row."""
        group = QWidget(self.widget)
        col = QVBoxLayout(group)
        col.setContentsMargins(1, 0, IMAGE_GEN_FIELD_BORDER_PAD, 0)
        col.setSpacing(IMAGE_GEN_FIELD_LABEL_SPACING)
        display_control = control
        if isinstance(control, QPlainTextEdit):
            col.addWidget(
                make_image_gen_prompt_label_row(label_text, control, group),
                0,
            )
            control.setSizePolicy(
                QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum
            )
            configure_image_gen_prompt_edit(control)
            display_control = wrap_image_gen_prompt_row_with_copy(
                control, control
            )
        else:
            col.addWidget(make_image_gen_field_label(label_text, group), 0)
            display_control.setSizePolicy(
                QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
            )
            if display_control.minimumHeight() < 1:
                fm = display_control.fontMetrics()
                display_control.setFixedHeight(
                    image_gen_prompt_height_for_lines(
                        IMAGE_GEN_PROMPT_MAX_LINE_COUNT, fm
                    )
                )
        col.addWidget(
            wrap_image_gen_field_control_indent(
                wrap_image_gen_bordered_field(display_control), group
            ),
            0,
        )
        group.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum
        )
        self._prompt_group = group
        insert_at = self._layout.count()
        if self._below_row_in_layout:
            insert_at = max(0, self._layout.indexOf(self._below_row))
        self._layout.insertWidget(insert_at, group)

    def prompt_editor_host_widget(self) -> Optional[QWidget]:
        """Indented prompt editor wrapper (direct child of the prompt field group)."""
        if self._prompt_group is None:
            return None
        copy_btn = self._prompt_group.findChild(QPushButton, "imageGenPromptCopyBtn")
        if copy_btn is None:
            return None
        widget: Optional[QWidget] = copy_btn
        while widget is not None:
            parent = widget.parentWidget()
            if parent is self._prompt_group:
                return widget
            if parent is None:
                break
            widget = parent
        return None

    def prompt_field_label_widget(self) -> Optional[QLabel]:
        if self._prompt_group is None:
            return None
        return self._prompt_group.findChild(QLabel, IMAGE_GEN_FIELD_LABEL_OBJECT_NAME)

    def prompt_field_label_row_widget(self) -> Optional[QWidget]:
        if self._prompt_group is None:
            return None
        return self._prompt_group.findChild(QWidget, "imageGenPromptLabelRow")

    def mount_system_prompt_below_image_prompt(self, system_prompt_widget: QWidget) -> None:
        """Image Prompt first (label, editor, import row), then system prompt block."""
        if self._prompt_group is None:
            return
        col = self._prompt_group.layout()
        if col is None:
            return
        prompt_label_row = self.prompt_field_label_row_widget()
        if prompt_label_row is None:
            prompt_label_row = self.prompt_field_label_widget()
        prompt_editor = self.prompt_editor_host_widget()
        if prompt_label_row is None or prompt_editor is None:
            return

        image_section: list[QWidget] = [prompt_label_row, prompt_editor]
        if (
            self._prompt_import_host is not None
            and col.indexOf(self._prompt_import_host) >= 0
        ):
            image_section.append(self._prompt_import_host)

        system_prompt_widget.setParent(self._prompt_group)
        for widget in image_section + [system_prompt_widget]:
            if col.indexOf(widget) >= 0:
                col.removeWidget(widget)

        for i, widget in enumerate(image_section):
            col.insertWidget(i, widget, 0)
        col.insertWidget(len(image_section), system_prompt_widget, 0)

    def mount_prompt_import_row(self, row: Optional[QWidget]) -> None:
        """Import buttons directly under the image prompt editor."""
        if self._prompt_group is None:
            return
        col = self._prompt_group.layout()
        if col is None:
            return
        if self._prompt_import_host is not None:
            col.removeWidget(self._prompt_import_host)
            self._prompt_import_host.deleteLater()
            self._prompt_import_host = None
        if row is None:
            return
        prompt_editor = self.prompt_editor_host_widget()
        if prompt_editor is None:
            return
        host = wrap_image_gen_prompt_subsection(row, self._prompt_group)
        self._prompt_import_host = host
        idx = col.indexOf(prompt_editor)
        if idx < 0:
            col.addWidget(host, 0)
        else:
            col.insertWidget(idx + 1, host, 0)

    def replace_prompt_editor_widget(self, new_widget: QWidget) -> None:
        """Replace the bordered prompt editor area with new_widget (e.g. splitter)."""
        if self._prompt_group is None:
            return
        col = self._prompt_group.layout()
        if col is None or col.count() < 2:
            return
        item = col.itemAt(1)
        old = item.widget() if item is not None else None
        if old is not None:
            col.removeWidget(old)
            old.setParent(None)
        col.addWidget(new_widget, 0)

    def add_labeled_field(
        self,
        label_text: Optional[str],
        control: QWidget,
        *,
        stretch_control: bool = True,
        to_outer: bool = False,
        copy_from_edit: Optional[QPlainTextEdit] = None,
    ) -> QWidget:
        parent = self.widget if to_outer else self._controls_host
        group = QWidget(parent)
        col = QVBoxLayout(group)
        edge_pad = IMAGE_GEN_FIELD_BORDER_PAD if to_outer else 0
        col.setContentsMargins(1, 0, edge_pad, 0)
        col.setSpacing(IMAGE_GEN_FIELD_LABEL_SPACING)
        if label_text:
            col.addWidget(make_image_gen_field_label(label_text, group), 0)
        display_control = control
        if copy_from_edit is not None:
            display_control = wrap_image_gen_prompt_row_with_copy(
                control, copy_from_edit
            )
        if stretch_control:
            display_control.setSizePolicy(
                QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
            )
            group.setSizePolicy(
                QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
            )
        else:
            group.setSizePolicy(
                QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed
            )
        if label_text:
            col.addWidget(
                wrap_image_gen_field_control_indent(display_control, group), 0
            )
        elif stretch_control:
            col.addWidget(display_control, 0)
        else:
            col.addWidget(
                display_control,
                0,
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            )
        if to_outer:
            self._layout.addWidget(group)
        elif label_text:
            self._append_control_group(group)
        else:
            self._append_checkbox_group(group)
        return group

    def add_columns(
        self,
        columns: List[Tuple[str, QWidget]],
    ) -> None:
        row = QWidget(self._controls_host)
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(IMAGE_GEN_COLUMN_ROW_SPACING)
        for label_text, control in columns:
            row_layout.addWidget(
                _build_image_gen_column_cell(row, label_text, control), 1
            )
        self.add_group(row)

    def add_half_column_row(
        self,
        columns: List[Optional[Tuple[str, QWidget]]],
    ) -> None:
        """Steps/quant-style row: two half-width labeled fields, blank filler if absent."""
        group = QWidget(self._controls_host)
        col = QVBoxLayout(group)
        col.setContentsMargins(1, 0, 0, 0)
        col.setSpacing(0)
        col.addWidget(
            build_image_gen_half_column_row(columns, parent=group),
            0,
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop,
        )
        group.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        self._append_control_group(group)

    def add_checkbox_row(self, checkboxes: List[QWidget]) -> None:
        for checkbox in checkboxes:
            checkbox.setSizePolicy(
                QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed
            )
            self._append_checkbox_group(checkbox)


def mount_image_gen_fields_in_scroll(
    scroll: QScrollArea,
    panel: ImageGenFieldsPanel,
) -> None:
    """Mount fields in a scroll area with padding so borders are not clipped."""
    from imagegen_plugins.image_gen_dialog import apply_image_gen_preview_client_background

    scroll.setWidgetResizable(True)
    scroll.setHorizontalScrollBarPolicy(
        Qt.ScrollBarPolicy.ScrollBarAlwaysOff
    )
    scroll.setFrameShape(QScrollArea.Shape.NoFrame)
    apply_image_gen_preview_client_background(scroll)
    viewport = scroll.viewport()
    viewport.setAutoFillBackground(True)
    apply_image_gen_preview_client_background(viewport)
    scroll.setWidget(panel.widget)
    panel._scroll_area = scroll
    apply_image_gen_preview_client_background(panel.widget)
    panel.widget.setSizePolicy(
        QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum
    )
    QTimer.singleShot(0, panel.reflow_controls)


def image_gen_custom_size_group_stylesheet() -> str:
    """Tighter width/height rows inside the Custom Size group box."""
    sz = IMAGE_GEN_DIM_HELPER_BTN_SIZE
    return f"""
    #imageGenDialog QGroupBox#imageGenCustomSizeGroup {{
        margin-top: 6px;
        padding-top: 4px;
    }}
    #imageGenDialog QGroupBox#imageGenCustomSizeGroup QLabel#{IMAGE_GEN_FIELD_LABEL_OBJECT_NAME} {{
        padding-top: 0px;
        font-size: 12px;
    }}
    #imageGenDialog QWidget#imageGenCustomSizeDimRow StepSpinBox {{
        min-height: {sz}px;
        max-height: {sz}px;
    }}
    #imageGenDialog QWidget#imageGenCustomSizeDimRow QSlider::groove:horizontal {{
        height: 3px;
    }}
    #imageGenDialog QWidget#imageGenCustomSizeDimRow QSlider::handle:horizontal {{
        width: 7px;
        height: 7px;
        margin: -3px 0;
        border-radius: 3px;
    }}
    #imageGenDialog QGroupBox#imageGenCustomSizeGroup QPushButton#imageGenFieldResetBtn {{
        min-width: {sz}px;
        max-width: {sz}px;
        min-height: {sz}px;
        max-height: {sz}px;
    }}
    """


def image_gen_field_label_stylesheet() -> str:
    t = get_active_theme()
    return f"""
    #imageGenDialog QLabel#{IMAGE_GEN_FIELD_LABEL_OBJECT_NAME} {{
        color: {t.dialog_text_color_hex};
        font-size: {IMAGE_GEN_FIELD_LABEL_FONT_SIZE}px;
        font-weight: normal;
        padding-top: 4px;
        margin: 0px;
    }}
    #imageGenDialog StepSpinBox {{
        min-height: 30px;
        max-height: 30px;
        margin: 0px;
    }}
    #imageGenDialog StepSpinBox QLineEdit#StepSpinEdit {{
        padding: 1px 4px 1px 4px;
        font-size: 12px;
    }}
    #imageGenDialog QSlider::groove:horizontal {{
        height: 4px;
        border-radius: 2px;
        border: 1px solid {t.groupbox_border_hex};
        background: {t.groupbox_border_hex};
    }}
    #imageGenDialog QSlider::add-page:horizontal {{
        background: {t.groupbox_border_hex};
        border-radius: 2px;
    }}
    #imageGenDialog QSlider::groove:vertical {{
        width: 4px;
        border-radius: 2px;
        border: 1px solid {t.groupbox_border_hex};
        background: {t.groupbox_border_hex};
    }}
    #imageGenDialog QSlider::add-page:vertical {{
        background: {t.groupbox_border_hex};
        border-radius: 2px;
    }}
    #imageGenDialog QSlider::handle:horizontal {{
        background: {t.accent_color_hex};
        border: 1px solid {t.tab_button_focus_border_color_hex};
        width: 8px;
        height: 8px;
        margin: -4px 0;
        border-radius: 4px;
    }}
    #imageGenDialog QSlider::handle:horizontal:hover {{
        background: {t.tab_button_focus_border_color_hex};
        border-color: {t.qslider_handle_hover_border_hex};
    }}
    #imageGenDialog QSlider::handle:horizontal:focus {{
        border: 2px solid {t.qslider_handle_focus_border_hex};
    }}
    #imageGenDialog QCheckBox {{
        spacing: 6px;
        min-width: 0px;
    }}
    #imageGenDialog QComboBox {{
        min-height: 22px;
        padding: 2px 8px;
    }}
    #imageGenDialog QPlainTextEdit,
    #imageGenDialog QLineEdit {{
        padding: 5px 8px;
    }}
    """ + image_gen_custom_size_group_stylesheet() + image_gen_field_reset_btn_dialog_stylesheet() + image_gen_prompt_copy_btn_dialog_stylesheet() + image_gen_prompt_clear_btn_dialog_stylesheet() + image_gen_prompt_voice_mic_btn_dialog_stylesheet() + image_gen_system_prompt_copy_btn_dialog_stylesheet() + image_gen_system_prompt_clear_btn_dialog_stylesheet() + image_gen_system_prompt_voice_mic_btn_dialog_stylesheet()


