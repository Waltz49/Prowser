#!/usr/bin/env python3
"""Shared chat pane styling and icon action buttons."""

from __future__ import annotations

import os
from typing import Callable

from PySide6.QtCore import QEvent, QObject, QSize, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QDragEnterEvent,
    QDragMoveEvent,
    QDropEvent,
    QIcon,
    QImage,
    QPalette,
    QPixmap,
    qGray,
)
from PySide6.QtWidgets import QFrame, QGridLayout, QGroupBox, QPushButton, QSizePolicy, QWidget
from shiboken6 import isValid

from chat_plugins.chat_image_store import MAX_CHAT_IMAGES
from config import job_queue_cell_background_hex
from theme.theme_base import asset_path
from theme.theme_service import get_active_theme
from utils import validate_image_file

_ICON_BTN_SIZE = 22
_ICON_DISPLAY_PX = 14
CHAT_THUMB_PX = 64


def _local_paths_from_mime(mime) -> list[str]:
    if not mime.hasUrls():
        return []
    paths: list[str] = []
    for url in mime.urls():
        if url.isLocalFile():
            paths.append(os.path.abspath(url.toLocalFile()))
    return paths


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
        self.setAcceptDrops(True)
        from PySide6.QtGui import QPainter, QPen
        from PySide6.QtCore import QRect

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

    def _effective_allow_remove(self) -> bool:
        row = self.parent()
        if isinstance(row, ChatImageThumbRow):
            return row.effective_allow_remove()
        return self._allow_remove

    def enterEvent(self, event) -> None:
        self._hover_remove = self._effective_allow_remove()
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._hover_remove = False
        self.update()
        super().leaveEvent(event)

    def _remove_rect(self):
        if not self._effective_allow_remove():
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

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        row = self.parent()
        if isinstance(row, ChatImageThumbRow):
            row.dragEnterEvent(event)
            return
        event.ignore()

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:
        row = self.parent()
        if isinstance(row, ChatImageThumbRow):
            row.dragMoveEvent(event)
            return
        event.ignore()

    def dropEvent(self, event: QDropEvent) -> None:
        row = self.parent()
        if isinstance(row, ChatImageThumbRow):
            row.dropEvent(event)
            return
        event.ignore()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._hover_remove = self._effective_allow_remove()
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
            if isinstance(row, ChatImageThumbRow) and row.can_open_images():
                self.open_requested.emit()
                event.accept()
                return
        super().mousePressEvent(event)


class ChatImageThumbRow(QWidget):
    """Flowing row of up to four 64px thumbnails (wraps to fit pane width)."""

    images_changed = Signal(list)
    _THUMB_GAP = 4

    def __init__(self, parent=None, *, compact_row: bool = False, main_window=None):
        super().__init__(parent)
        self._paths: list[str] = []
        self._allow_remove = True
        self._allow_remove_when: Callable[[], bool] | None = None
        self._main_window = main_window
        self._last_grid_cols = -1
        self._last_emitted_paths: list[str] = []
        self._layout = QGridLayout(self)
        self._layout.setContentsMargins(0, 0, 0, self._THUMB_GAP)
        self._layout.setHorizontalSpacing(self._THUMB_GAP)
        self._layout.setVerticalSpacing(self._THUMB_GAP)
        self._layout.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop
        )
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setAcceptDrops(True)

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
            self.add_dropped_paths(paths)
            event.acceptProposedAction()
            return
        event.ignore()

    def _layout_width(self) -> int:
        """Width available for wrapping thumbs (parent inner width, not shrunken self width)."""
        cell = CHAT_THUMB_PX + self._THUMB_GAP
        width = self.contentsRect().width()
        parent = self.parentWidget()
        if parent is not None:
            inner = parent.width()
            lay = parent.layout()
            if lay is not None:
                m = lay.contentsMargins()
                inner -= m.left() + m.right()
            if inner > width:
                width = inner
        return max(width, cell)

    def can_open_images(self) -> bool:
        return self._main_window is not None and bool(self._paths)

    def effective_allow_remove(self) -> bool:
        if self._allow_remove_when is not None:
            return bool(self._allow_remove_when())
        return self._allow_remove

    def refresh_hover_under_cursor(self) -> None:
        from PySide6.QtGui import QCursor

        global_pos = QCursor.pos()
        for i in range(self._layout.count()):
            item = self._layout.itemAt(i)
            w = item.widget()
            if not isinstance(w, ChatImageThumb):
                continue
            local = w.mapFromGlobal(global_pos)
            if w.rect().contains(local):
                w._hover_remove = w._effective_allow_remove()
            else:
                w._hover_remove = False
            w.update()

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
        if not self._paths:
            return
        cols = self._cols_for_width(self._layout_width())
        if cols != self._last_grid_cols:
            self._rebuild()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if not self._paths:
            return
        cols = self._cols_for_width(self._layout_width())
        if cols != self._last_grid_cols:
            self._rebuild()

    def _cols_for_width(self, width: int) -> int:
        cell = CHAT_THUMB_PX + self._THUMB_GAP
        by_width = max(1, width // cell)
        return min(by_width, len(self._paths))

    def _apply_row_height(self, cols: int) -> None:
        if not self._paths:
            return
        rows = (len(self._paths) + cols - 1) // cols
        bottom = self._layout.contentsMargins().bottom()
        height = rows * CHAT_THUMB_PX + max(0, rows - 1) * self._THUMB_GAP + bottom
        self.setFixedHeight(height)

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
        cols = self._cols_for_width(self._layout_width())
        self._last_grid_cols = cols
        for c in range(cols):
            self._layout.setColumnStretch(c, 0)
            self._layout.setColumnMinimumWidth(c, CHAT_THUMB_PX)
        for idx, path in enumerate(self._paths):
            thumb = ChatImageThumb(path, self, allow_remove=allow_remove)
            thumb.remove_requested.connect(self._on_remove)
            if self._main_window is not None:
                thumb.open_requested.connect(self._open_attached_images)
                thumb.setCursor(Qt.CursorShape.PointingHandCursor)
            row = idx // cols
            col = idx % cols
            self._layout.addWidget(thumb, row, col)
        self.setVisible(True)
        self._apply_row_height(cols)
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


def chat_user_message_stylesheet() -> str:
    th = get_active_theme()
    bg = job_queue_cell_background_hex()
    border = th.groupbox_border_hex
    return f"""
        QGroupBox#chatUserBubble {{
            font-weight: normal;
            color: {th.dialog_text_color_hex};
            background-color: {bg};
            border: 2px solid {border};
            border-radius: 8px;
            margin: 0px;
            margin-top: 0px;
            padding: 8px;
        }}
        QGroupBox#chatUserBubble::title {{
            subcontrol-origin: margin;
            subcontrol-position: top left;
            padding: 0px;
            margin: 0px;
            height: 0px;
            border: none;
        }}
    """


def apply_chat_user_bubble_chrome(group: QGroupBox) -> None:
    """Paint user bubble like a group box (visible border on sidebar panes)."""
    th = get_active_theme()
    bg = job_queue_cell_background_hex()
    color = QColor(bg)
    if not color.isValid():
        color = QColor(th.sidebar_background_color_hex).lighter(110)
    group.setTitle("")
    group.setFlat(False)
    palette = group.palette()
    palette.setColor(QPalette.ColorRole.Window, color)
    group.setPalette(palette)
    group.setAutoFillBackground(True)
    group.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
    group.setStyleSheet(chat_user_message_stylesheet())


def chat_assistant_message_stylesheet() -> str:
    return """
        QFrame#chatAssistantBubble {
            background-color: transparent;
            border: none;
        }
    """


def chat_prompt_edit_stylesheet() -> str:
    th = get_active_theme()
    return f"""
        QPlainTextEdit {{
            background-color: {th.sidebar_background_color_hex};
            color: {th.dialog_text_color_hex};
            border: 1px solid {th.border_default_hex};
            border-radius: 6px;
            padding: 6px;
        }}
    """


def _icon_button_chrome_stylesheet() -> str:
    th = get_active_theme()
    sz = _ICON_BTN_SIZE
    btn_bg = th.sidebar_background_color_hex
    btn_hover = th.widget_bg_hover_hex
    return f"""
        QPushButton {{
            background-color: {btn_bg};
            border: 1px solid {th.border_default_hex};
            border-radius: 3px;
            padding: 0px;
            min-width: {sz}px;
            max-width: {sz}px;
            min-height: {sz}px;
            max-height: {sz}px;
        }}
        QPushButton:hover {{
            background-color: {btn_hover};
        }}
        QPushButton:disabled {{
            opacity: 0.35;
        }}
    """


def _load_icon_pixmap(icon_name: str, size_px: int) -> QPixmap:
    pixmap = QPixmap(asset_path(icon_name))
    if pixmap.isNull():
        return QPixmap()
    return pixmap.scaled(
        size_px,
        size_px,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )


def _grayscale_pixmap(pixmap: QPixmap) -> QPixmap:
    image = pixmap.toImage().convertToFormat(QImage.Format.Format_ARGB32)
    for y in range(image.height()):
        for x in range(image.width()):
            color = QColor(image.pixelColor(x, y))
            if color.alpha() == 0:
                continue
            gray = qGray(color.rgb())
            image.setPixelColor(x, y, QColor(gray, gray, gray, color.alpha()))
    return QPixmap.fromImage(image)


class _ChatIconButtonHover(QObject):
    def __init__(
        self,
        button: QPushButton,
        normal_icon: QIcon,
        hover_icon: QIcon,
    ) -> None:
        super().__init__(button)
        self._button = button
        self._normal_icon = normal_icon
        self._hover_icon = hover_icon
        button.installEventFilter(self)

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        if event.type() == QEvent.Type.Destroy:
            if obj is self._button and isValid(self._button):
                self._button.removeEventFilter(self)
            return False
        if not isValid(self._button):
            return False
        if obj is self._button:
            if event.type() == QEvent.Type.HoverEnter:
                self._button.setIcon(self._hover_icon)
            elif event.type() == QEvent.Type.HoverLeave:
                self._button.setIcon(self._normal_icon)
        return False


def _create_chat_icon_button(
    parent,
    icon_name: str,
    *,
    hover_icon_name: str | None = None,
    tooltip: str = "",
) -> QPushButton:
    btn = QPushButton(parent)
    btn.setToolTip(tooltip)
    icon_px = _ICON_DISPLAY_PX
    base = _load_icon_pixmap(icon_name, icon_px)
    hover_name = hover_icon_name or icon_name.replace(".png", "_hover.png")
    hover_pm = (
        _load_icon_pixmap(hover_name, icon_px)
        if os.path.isfile(asset_path(hover_name))
        else base
    )
    normal_icon = QIcon(_grayscale_pixmap(base))
    hover_icon = QIcon(hover_pm)
    btn.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
    btn.setIcon(normal_icon)
    btn.setIconSize(QSize(icon_px, icon_px))
    btn.setStyleSheet(_icon_button_chrome_stylesheet())
    _ChatIconButtonHover(btn, normal_icon, hover_icon)
    return btn


def create_chat_edit_button(parent=None):
    return _create_chat_icon_button(
        parent,
        "edit_icon.png",
        tooltip="Edit message",
    )


def create_chat_redo_button(parent=None):
    return _create_chat_icon_button(
        parent,
        "dim_reverse_icon.png",
        tooltip="Regenerate response",
    )


def create_chat_delete_button(parent=None):
    return _create_chat_icon_button(
        parent,
        "trash_icon.png",
        hover_icon_name="trash_icon_hover.png",
        tooltip="Delete message",
    )


def create_chat_from_text_button(parent=None):
    return _create_chat_icon_button(
        parent,
        "fromText.png",
        hover_icon_name="fromText_hover.png",
        tooltip="Create an image from text with this message as the prompt",
    )


def chat_create_from_text_available() -> bool:
    try:
        from imagegen_plugins.image_gen_menu import imagegen_create_from_text_available

        return imagegen_create_from_text_available()
    except ImportError:
        return False
