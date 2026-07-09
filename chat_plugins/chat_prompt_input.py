#!/usr/bin/env python3
"""Auto-growing prompt field with image drop support for the chat pane."""

from __future__ import annotations

import os
from typing import Callable, Optional

from PySide6.QtCore import QEvent, QObject, Qt, Signal
from PySide6.QtGui import QDragEnterEvent, QDragMoveEvent, QDropEvent, QTextBlock, QTextLayout, QTextOption
from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QPlainTextEdit, QSizePolicy, QVBoxLayout, QWidget

from chat_plugins.chat_image_store import MAX_CHAT_IMAGES
from chat_plugins.chat_ui_common import CHAT_THUMB_PX, chat_prompt_edit_stylesheet
from theme.theme_service import get_active_theme
from utils import validate_image_file

CHAT_PROMPT_MIN_LINES = 2
CHAT_PROMPT_MAX_LINES = 12
_PROMPT_STYLE_PADDING_V = 12
_PROMPT_STYLE_BORDER_V = 2


def _local_paths_from_mime(mime) -> list[str]:
    if not mime.hasUrls():
        return []
    paths: list[str] = []
    for url in mime.urls():
        if url.isLocalFile():
            paths.append(os.path.abspath(url.toLocalFile()))
    return paths


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


class ChatImageThumb(QWidget):
    """64px image thumbnail with hover delete affordance."""

    remove_requested = Signal(str)
    open_requested = Signal()

    _REMOVE_BOX_PX = 24
    _REMOVE_INSET_PX = 2

    def __init__(self, image_path: str, parent=None, *, allow_remove: bool = True):
        super().__init__(parent)
        self._image_path = os.path.abspath(image_path)
        self._allow_remove = allow_remove
        self._hover_remove = False
        self.setFixedSize(CHAT_THUMB_PX, CHAT_THUMB_PX)
        self.setMouseTracking(True)
        from PySide6.QtGui import QPixmap, QPainter, QColor, QPen
        from PySide6.QtCore import QRect

        self._QPixmap = QPixmap
        self._QPainter = QPainter
        self._QColor = QColor
        self._QPen = QPen
        self._QRect = QRect
        self._pixmap = QPixmap(image_path)
        if self._pixmap.isNull():
            self._scaled = None
        else:
            self._scaled = self._pixmap.scaled(
                CHAT_THUMB_PX,
                CHAT_THUMB_PX,
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation,
            )

    def image_path(self) -> str:
        return self._image_path

    def enterEvent(self, event) -> None:
        self._hover_remove = self._allow_remove
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._hover_remove = False
        self.update()
        super().leaveEvent(event)

    def _remove_rect(self):
        if not self._allow_remove:
            return None
        box = self._REMOVE_BOX_PX
        inset = self._REMOVE_INSET_PX
        return self._QRect(
            self.width() - inset - box,
            inset,
            box,
            box,
        )

    def paintEvent(self, event) -> None:
        painter = self._QPainter(self)
        th = get_active_theme()
        painter.fillRect(self.rect(), th.sidebar_background_color_hex)
        if self._scaled is not None and not self._scaled.isNull():
            x = (self.width() - self._scaled.width()) // 2
            y = (self.height() - self._scaled.height()) // 2
            painter.drawPixmap(x, y, self._scaled)
        if self._hover_remove:
            remove_rect = self._remove_rect()
            if remove_rect is not None:
                painter.setRenderHint(self._QPainter.RenderHint.Antialiasing, True)
                painter.fillRect(remove_rect, self._QColor(255, 255, 255))
                inner = remove_rect.adjusted(2, 2, -2, -2)
                painter.fillRect(inner, self._QColor(0, 0, 0))
                pad = 2
                x_rect = inner.adjusted(pad, pad, -pad, -pad)
                painter.setPen(self._QPen(self._QColor(220, 40, 40), 2))
                painter.drawLine(x_rect.topLeft(), x_rect.bottomRight())
                painter.drawLine(x_rect.topRight(), x_rect.bottomLeft())

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            remove_rect = self._remove_rect()
            if (
                self._hover_remove
                and remove_rect is not None
                and remove_rect.contains(event.pos())
            ):
                self.remove_requested.emit(self._image_path)
                event.accept()
                return
            row = self.parent()
            if (
                isinstance(row, ChatImageThumbRow)
                and row._main_window is not None
            ):
                self.open_requested.emit()
                event.accept()
                return
        super().mousePressEvent(event)


class ChatImageThumbRow(QWidget):
    """Flowing row of up to four 64px thumbnails."""

    images_changed = Signal(list)

    def __init__(self, parent=None, *, compact_row: bool = False, main_window=None):
        super().__init__(parent)
        self._paths: list[str] = []
        self._allow_remove = True
        self._compact_row = compact_row
        self._main_window = main_window
        self._last_grid_cols = -1
        self._last_emitted_paths: list[str] = []
        if compact_row:
            self._layout = QHBoxLayout(self)
            self._layout.setContentsMargins(0, 0, 0, 4)
            self._layout.setSpacing(4)
            self._layout.setAlignment(
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop
            )
            self.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
            self.setFixedHeight(CHAT_THUMB_PX + 4)
        else:
            self._layout = QGridLayout(self)
            self._layout.setContentsMargins(0, 0, 0, 4)
            self._layout.setHorizontalSpacing(4)
            self._layout.setVerticalSpacing(4)
            self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def set_main_window(self, main_window) -> None:
        self._main_window = main_window
        self._sync_open_tooltip()

    def image_paths(self) -> list[str]:
        return list(self._paths)

    def set_image_paths(self, paths: list[str], *, allow_remove: bool = True) -> None:
        self._allow_remove = allow_remove
        self._paths = [os.path.abspath(p) for p in paths if p][:MAX_CHAT_IMAGES]
        self._rebuild()

    def clear_images(self) -> None:
        self._paths = []
        self._rebuild()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self._paths and not self._compact_row:
            cols = max(1, self.width() // (CHAT_THUMB_PX + 4))
            if cols != self._last_grid_cols:
                self._last_grid_cols = cols
                self._rebuild()

    def _emit_images_changed_if_needed(self) -> None:
        paths = self.image_paths()
        if paths == self._last_emitted_paths:
            return
        self._last_emitted_paths = list(paths)
        self.images_changed.emit(paths)

    def _clear_layout(self) -> None:
        while self._layout.count():
            item = self._layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

    def _rebuild(self) -> None:
        allow_remove = self._allow_remove
        self._clear_layout()
        if not self._paths:
            self.setVisible(False)
            self._last_grid_cols = -1
            self._emit_images_changed_if_needed()
            return
        if not self._compact_row:
            self._last_grid_cols = max(1, self.width() // (CHAT_THUMB_PX + 4))
        for idx, path in enumerate(self._paths):
            thumb = ChatImageThumb(path, self, allow_remove=allow_remove)
            thumb.remove_requested.connect(self._on_remove)
            if self._main_window is not None:
                thumb.open_requested.connect(self._open_attached_images)
                thumb.setCursor(Qt.CursorShape.PointingHandCursor)
            if self._compact_row:
                self._layout.addWidget(thumb)
            else:
                cols = self._last_grid_cols
                row = idx // cols
                col = idx % cols
                self._layout.addWidget(thumb, row, col)
        self.setVisible(True)
        self._emit_images_changed_if_needed()
        self._sync_open_tooltip()

    def _sync_open_tooltip(self) -> None:
        if self._main_window is None or not self._paths:
            self.setToolTip("")
            return
        if len(self._paths) == 1:
            self.setToolTip("Open image in browse view")
        else:
            self.setToolTip("Open images in thumbnail view")

    def _open_attached_images(self) -> None:
        if self._main_window is None or not self._paths:
            return
        from chat_plugins.chat_image_nav import open_chat_image_paths

        open_chat_image_paths(self._main_window, self._paths)

    def _on_remove(self, path: str) -> None:
        ap = os.path.abspath(path)
        self._paths = [p for p in self._paths if os.path.abspath(p) != ap]
        self._rebuild()

    def add_dropped_paths(self, incoming: list[str]) -> list[str]:
        added: list[str] = []
        for path in incoming:
            if len(self._paths) >= MAX_CHAT_IMAGES:
                break
            if not path or not os.path.isfile(path):
                continue
            if not validate_image_file(path):
                continue
            ap = os.path.abspath(path)
            if ap in self._paths:
                continue
            self._paths.append(ap)
            added.append(ap)
        self._rebuild()
        return added


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
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
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

    def __init__(self, parent=None, *, main_window=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 4, 6, 6)
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

    def _on_submit(self) -> None:
        text = self._edit.toPlainText().strip()
        images = self._thumb_row.image_paths()
        if not text and not images:
            return
        self.submit_requested.emit(text, images)
        self.clear_content()
