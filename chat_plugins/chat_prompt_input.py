#!/usr/bin/env python3
"""Auto-growing prompt field with image drop support for the chat pane."""

from __future__ import annotations

from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtGui import QDragEnterEvent, QDragMoveEvent, QDropEvent, QTextBlock, QTextLayout, QTextOption
from PySide6.QtWidgets import QPlainTextEdit, QVBoxLayout, QWidget

from chat_plugins.chat_ui_common import (
    ChatImageThumbRow,
    _local_paths_from_mime,
    chat_prompt_edit_stylesheet,
)
from browser_window.managers.window_event_filters import CURSOR_PEEK_ZONE_HEIGHT
from settings.widgets.macos_preferences import MacPreferenceCompactToggleRow
from theme.theme_service import get_active_theme

CHAT_PROMPT_MIN_LINES = 2
CHAT_PROMPT_MAX_LINES = 12
CHAT_PROMPT_BOTTOM_PADDING_EXTRA_PX = 10
CHAT_PROMPT_BOTTOM_PADDING_PX = (
    CHAT_PROMPT_BOTTOM_PADDING_EXTRA_PX + CURSOR_PEEK_ZONE_HEIGHT
)
_PROMPT_STYLE_PADDING_V = 12
_PROMPT_STYLE_BORDER_V = 2


def _prompt_text_width(edit: QPlainTextEdit) -> int:
    viewport_w = edit.viewport().width()
    if viewport_w > 1:
        return viewport_w
    frame = edit.frameWidth() * 2
    margins = edit.contentsMargins().left() + edit.contentsMargins().right()
    return max(1, edit.width() - frame - margins - 8)


def _block_line_count(block: QTextBlock, text_width: int) -> int:
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


def _content_line_count(edit: QPlainTextEdit) -> int:
    doc = edit.document()
    text_width = _prompt_text_width(edit)
    doc.setTextWidth(text_width)
    total = 0
    block = doc.firstBlock()
    while block.isValid():
        total += _block_line_count(block, text_width)
        block = block.next()
    return max(1, total)


def _height_for_lines(edit: QPlainTextEdit, line_count: int) -> int:
    lines = max(1, int(line_count))
    fm = edit.fontMetrics()
    return (
        fm.lineSpacing() * lines
        + fm.lineSpacing() // 2
        + _PROMPT_STYLE_PADDING_V
        + _PROMPT_STYLE_BORDER_V
        + 2
    )


class ChatPromptPlainTextEdit(QPlainTextEdit):
    """Auto-height plain text edit accepting image drops."""

    submit_requested = Signal()
    images_dropped = Signal(list)

    def __init__(
        self,
        parent=None,
        *,
        min_lines: int = CHAT_PROMPT_MIN_LINES,
        max_lines: int = CHAT_PROMPT_MAX_LINES,
    ):
        super().__init__(parent)
        self._min_lines = max(1, min_lines)
        self._max_lines = max(self._min_lines, max_lines)
        self._updating_height = False
        self._last_layout_width = -1
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self.setAcceptDrops(True)
        self.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self.setTabChangesFocus(False)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setStyleSheet(chat_prompt_edit_stylesheet())
        self.document().contentsChanged.connect(self._apply_height)
        self.installEventFilter(self)

    def eventFilter(self, obj, event) -> bool:
        if obj is self and event.type() == QEvent.Type.Resize:
            width = _prompt_text_width(self)
            if width > 1 and width != self._last_layout_width:
                self._last_layout_width = width
                self._apply_height()
        if obj is self and event.type() == QEvent.Type.KeyPress:
            if (
                event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter)
                and event.modifiers() & Qt.KeyboardModifier.ShiftModifier
            ):
                return False
            if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                self.submit_requested.emit()
                return True
        return super().eventFilter(obj, event)

    def _apply_height(self) -> None:
        if self._updating_height:
            return
        text_width = _prompt_text_width(self)
        if text_width <= 1:
            return
        self._updating_height = True
        try:
            lines = _content_line_count(self)
            lines = max(self._min_lines, min(lines, self._max_lines))
            at_max = _content_line_count(self) >= self._max_lines
            policy = (
                Qt.ScrollBarPolicy.ScrollBarAsNeeded
                if at_max
                else Qt.ScrollBarPolicy.ScrollBarAlwaysOff
            )
            if self.verticalScrollBarPolicy() != policy:
                self.setVerticalScrollBarPolicy(policy)
            height = _height_for_lines(self, lines)
            if self.height() != height:
                self.setFixedHeight(height)
                self.updateGeometry()
        finally:
            self._updating_height = False

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if _local_paths_from_mime(event.mimeData()):
            event.acceptProposedAction()
            return
        event.ignore()

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:
        if _local_paths_from_mime(event.mimeData()):
            event.acceptProposedAction()
            return
        event.ignore()

    def dropEvent(self, event: QDropEvent) -> None:
        paths = _local_paths_from_mime(event.mimeData())
        if paths:
            self.images_dropped.emit(paths)
            event.acceptProposedAction()
            return
        event.ignore()


class ChatPromptInput(QWidget):
    """Bottom input area: optional image row + auto-growing text field."""

    submit_requested = Signal(str, list)
    images_changed = Signal(list)
    automatic_create_toggled = Signal(bool)

    def __init__(self, parent=None, *, main_window=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 4, 6, CHAT_PROMPT_BOTTOM_PADDING_EXTRA_PX)
        layout.setSpacing(4)
        self._thumb_row = ChatImageThumbRow(
            self, compact_row=True, main_window=main_window
        )
        self._thumb_row.hide()
        layout.addWidget(self._thumb_row)
        self._edit = ChatPromptPlainTextEdit(self)
        self._edit.setPlaceholderText("Message…  (Enter to send, Shift+Enter for newline)")
        self._edit.submit_requested.connect(self._on_submit)
        self._edit.images_dropped.connect(self._thumb_row.add_dropped_paths)
        self._thumb_row.images_changed.connect(self.images_changed.emit)
        layout.addWidget(self._edit)
        self._automatic_create_row = MacPreferenceCompactToggleRow(
            "Submit Job Automatically",
            tooltip=(
                "When on, chat messages with images or /create automatically "
                "submit an image-generation job."
            ),
            parent=self,
        )
        self._automatic_create_row.setFixedHeight(CURSOR_PEEK_ZONE_HEIGHT)
        self._automatic_create_row.layout().setContentsMargins(6, 2, 6, 2)
        self._automatic_create_row.toggle.toggled.connect(self._on_automatic_create_toggled)
        layout.addWidget(self._automatic_create_row)
        self._automatic_create_active = False
        self._style_automatic_create_row()

    def set_main_window(self, main_window) -> None:
        self._thumb_row.set_main_window(main_window)

    def text_edit(self) -> ChatPromptPlainTextEdit:
        return self._edit

    def image_paths(self) -> list[str]:
        return self._thumb_row.image_paths()

    def set_content(self, text: str, image_paths: list[str] | None = None) -> None:
        self._edit.setPlainText(text or "")
        if image_paths is not None:
            self._thumb_row.set_image_paths(image_paths, allow_remove=True)
        self._edit.setFocus()

    def clear_content(self) -> None:
        self._edit.clear()
        self._thumb_row.clear_images()

    def set_automatic_create_active(self, active: bool) -> None:
        self._automatic_create_active = bool(active)
        toggle = self._automatic_create_row.toggle
        if toggle.isChecked() != self._automatic_create_active:
            toggle.blockSignals(True)
            toggle.setChecked(self._automatic_create_active)
            toggle.blockSignals(False)

    def refresh_theme_styles(self) -> None:
        self._edit.setStyleSheet(chat_prompt_edit_stylesheet())
        self._style_automatic_create_row()

    def _style_automatic_create_row(self) -> None:
        th = get_active_theme()
        self._automatic_create_row.setStyleSheet(
            f"""
            QLabel#macPreferenceRowTitle {{
                color: {th.sidebar_text_color_hex};
                font-size: 12pt;
                background: transparent;
            }}
            """
        )

    def _on_automatic_create_toggled(self, checked: bool) -> None:
        if checked == self._automatic_create_active:
            return
        self._automatic_create_active = checked
        self.automatic_create_toggled.emit(checked)

    def _on_submit(self) -> None:
        text = self._edit.toPlainText().strip()
        images = self._thumb_row.image_paths()
        if not text and not images:
            return
        self.submit_requested.emit(text, images)
        self.clear_content()
