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
    QFont,
    QFontMetrics,
    QIcon,
    QImage,
    QKeyEvent,
    QPainter,
    QPalette,
    QPen,
    QPixmap,
    QTextDocument,
    qGray,
)
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QGridLayout,
    QGroupBox,
    QLabel,
    QPushButton,
    QSizePolicy,
    QWidget,
)
from shiboken6 import isValid

from chat_plugins.chat_image_store import MAX_CHAT_IMAGES
from config import job_queue_cell_background_hex
from theme.theme import macos_scrollbar_for_surface
from theme.theme_base import asset_path
from theme.theme_service import get_active_theme
from utils import validate_image_file

_ICON_BTN_SIZE = 22
_ICON_DISPLAY_PX = 14
CHAT_THUMB_PX = 64


def cmd_enter_pressed(event: QKeyEvent) -> bool:
    if event.key() not in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
        return False
    mods = event.modifiers() & ~Qt.KeyboardModifier.KeypadModifier
    cmd = mods & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.MetaModifier)
    if not cmd:
        return False
    other = mods & ~(
        Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.MetaModifier
    )
    return other in (Qt.KeyboardModifier.NoModifier, 0)


class CmdEnterAcceptFilter(QObject):
    """Accept a dialog when the user presses Cmd/Ctrl+Return in a text field."""

    def __init__(self, dialog: QDialog) -> None:
        super().__init__(dialog)
        self._dialog = dialog

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if (
            event.type() == QEvent.Type.KeyPress
            and isinstance(event, QKeyEvent)
            and cmd_enter_pressed(event)
        ):
            self._dialog.accept()
            return True
        return super().eventFilter(watched, event)


def install_cmd_enter_accept(dialog: QDialog, *widgets: QWidget) -> None:
    filt = CmdEnterAcceptFilter(dialog)
    for widget in widgets:
        widget.installEventFilter(filt)


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
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
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

    def mouseMoveEvent(self, event) -> None:
        if self._effective_allow_remove():
            hover = self.rect().contains(event.pos())
            if hover != self._hover_remove:
                self._hover_remove = hover
                self.update()
        super().mouseMoveEvent(event)

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

    def set_image_paths(
        self,
        paths: list[str],
        *,
        allow_remove: bool = True,
        force: bool = False,
    ) -> None:
        new_paths = [os.path.abspath(p) for p in (paths or []) if p][:MAX_CHAT_IMAGES]
        self._allow_remove = allow_remove
        if not force and new_paths == self._paths:
            if self.effective_allow_remove():
                self.refresh_hover_under_cursor()
            return
        self._paths = new_paths
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
        if self.effective_allow_remove():
            self.refresh_hover_under_cursor()

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
    bg = th.sidebar_background_color_hex
    return f"""
        QPlainTextEdit, QTextEdit {{
            background-color: {bg};
            color: {th.dialog_text_color_hex};
            border: 1px solid {th.border_default_hex};
            border-radius: 6px;
            padding: 6px;
        }}
        {macos_scrollbar_for_surface(th, bg)}
    """



CHAT_PROMPT_LIBRARY_PREVIEW_MAX_LINES = 4
_PROMPT_PREVIEW_STYLE_PADDING_V = 12
_PROMPT_PREVIEW_STYLE_BORDER_V = 2


def chat_prompt_preview_stylesheet() -> str:
    th = get_active_theme()
    return f"""
        QLabel#chatPromptLibraryPreview {{
            background-color: {th.sidebar_background_color_hex};
            color: {th.dialog_text_color_hex};
            border: 1px solid {th.border_default_hex};
            border-radius: 6px;
            padding: 6px;
        }}
    """


def _wrapped_line_count_at_width(text: str, font: QFont, width: int) -> int:
    doc = QTextDocument()
    doc.setDefaultFont(font)
    doc.setPlainText(text.replace("\r\n", "\n").replace("\r", "\n"))
    if width > 1:
        doc.setTextWidth(float(width))
    fm = QFontMetrics(font)
    line_h = max(1, fm.lineSpacing())
    layout = doc.documentLayout()
    total = 0
    block = doc.firstBlock()
    while block.isValid():
        br = layout.blockBoundingRect(block)
        total += max(1, int((br.height() + line_h - 1) // line_h))
        block = block.next()
    return max(1, total)


def elide_prompt_library_preview(
    text: str,
    font: QFont,
    width: int,
    max_lines: int = CHAT_PROMPT_LIBRARY_PREVIEW_MAX_LINES,
) -> str:
    plain = (text or "(empty prompt)").replace("\r\n", "\n").replace("\r", "\n")
    if width <= 1 or _wrapped_line_count_at_width(plain, font, width) <= max_lines:
        return plain

    fm = QFontMetrics(font)
    lo, hi = 0, len(plain)
    best = 0
    while lo <= hi:
        mid = (lo + hi) // 2
        candidate = plain[:mid].rstrip("\n")
        if _wrapped_line_count_at_width(candidate, font, width) <= max_lines:
            best = mid
            lo = mid + 1
        else:
            hi = mid - 1

    trimmed = plain[:best].rstrip("\n")
    if not trimmed:
        return fm.elidedText(plain, Qt.TextElideMode.ElideRight, width)

    if best < len(plain.rstrip()):
        lines = trimmed.split("\n")
        last = lines[-1] if lines else ""
        lines[-1] = fm.elidedText(
            last.rstrip() + "…",
            Qt.TextElideMode.ElideRight,
            width,
        )
        return "\n".join(lines)
    return trimmed


def prompt_library_preview_height_px(
    font: QFont,
    lines: int = CHAT_PROMPT_LIBRARY_PREVIEW_MAX_LINES,
) -> int:
    fm = QFontMetrics(font)
    return (
        fm.lineSpacing() * lines
        + _PROMPT_PREVIEW_STYLE_PADDING_V
        + _PROMPT_PREVIEW_STYLE_BORDER_V
    )


class ChatPromptLibraryPreview(QLabel):
    """Read-only multi-line prompt preview for system/user prompt library dialogs."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("chatPromptLibraryPreview")
        self._full_text = ""
        self.setWordWrap(True)
        self.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setStyleSheet(chat_prompt_preview_stylesheet())

    def set_prompt_text(self, text: str) -> None:
        self._full_text = text
        self._refresh()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._refresh()

    def _refresh(self) -> None:
        font = self.font()
        self.setFixedHeight(
            prompt_library_preview_height_px(font, CHAT_PROMPT_LIBRARY_PREVIEW_MAX_LINES)
        )
        width = self.contentsRect().width()
        if width > 1:
            self.setText(elide_prompt_library_preview(self._full_text, font, width))
        else:
            self.setText(self._full_text or "(empty prompt)")


_CHAT_LIBRARY_ICON_BTN_SIZE = 22


def _chat_library_icon_button_stylesheet(
    icon_name: str,
    *,
    hover_icon_name: str | None = None,
) -> str:
    icon_url = f"url({asset_path(icon_name)})"
    if hover_icon_name:
        hover_url = f"url({asset_path(hover_icon_name)})"
    else:
        hover_url = icon_url.replace(".png", "_hover.png")
    sz = _CHAT_LIBRARY_ICON_BTN_SIZE
    return f"""
        QPushButton {{
            background-color: transparent;
            border: none;
            border-radius: 3px;
            padding: 0px;
            min-width: {sz}px;
            max-width: {sz}px;
            min-height: {sz}px;
            max-height: {sz}px;
            image: {icon_url};
        }}
        QPushButton:hover {{
            background-color: transparent;
            border: none;
            image: {hover_url};
        }}
        QPushButton:pressed {{
            background-color: transparent;
        }}
    """


def chat_library_edit_button_stylesheet() -> str:
    return _chat_library_icon_button_stylesheet(
        "edit_icon.png",
        hover_icon_name="edit_icon_hover.png",
    )


def chat_library_trash_button_stylesheet() -> str:
    return _chat_library_icon_button_stylesheet(
        "trash_icon.png",
        hover_icon_name="trash_icon_hover.png",
    )


def _icon_button_chrome_stylesheet() -> str:
    th = get_active_theme()
    sz = _ICON_BTN_SIZE
    btn_bg = th.sidebar_background_color_hex
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
            background-color: {th.button_bg_hover_hex};
            border: 1px solid {th.button_border_hover_hex};
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


def _pixmap_matte_black_transparent(pixmap: QPixmap, *, threshold: int = 42) -> QPixmap:
    """Drop near-black matte backgrounds from chat asset PNGs."""
    if pixmap.isNull():
        return pixmap
    image = pixmap.toImage().convertToFormat(QImage.Format.Format_ARGB32)
    for y in range(image.height()):
        for x in range(image.width()):
            color = QColor(image.pixelColor(x, y))
            if color.alpha() == 0:
                continue
            if (
                color.red() <= threshold
                and color.green() <= threshold
                and color.blue() <= threshold
            ):
                color.setAlpha(0)
                image.setPixelColor(x, y, color)
    return QPixmap.fromImage(image)


def _load_chat_asset_icon_pixmap(
    icon_name: str,
    *,
    size_px: int = _ICON_DISPLAY_PX,
    matte_black: bool = False,
) -> QPixmap:
    pixmap = QPixmap(asset_path(icon_name))
    if pixmap.isNull():
        return QPixmap()
    if matte_black:
        pixmap = _pixmap_matte_black_transparent(pixmap)
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
        button.setIcon(normal_icon)

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
        tooltip=(
            "Create an image from text with\n"
            "this message as the prompt\n"
            "(⌥-click to generate immediately)"
        ),
    )


def _draw_chat_stop_x_icon(painter: QPainter, size: int) -> None:
    """Corner-to-corner red X (same stroke as chat image-thumb delete overlay)."""
    pad = 2
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setPen(QPen(QColor(220, 40, 40), 2))
    painter.drawLine(pad, pad, size - pad, size - pad)
    painter.drawLine(size - pad, pad, pad, size - pad)


def _chat_stop_icon_pixmap(*, size_px: int = _ICON_DISPLAY_PX) -> QPixmap:
    pixmap = QPixmap(size_px, size_px)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    _draw_chat_stop_x_icon(painter, size_px)
    painter.end()
    return pixmap


def create_chat_stop_button(parent=None):
    """Stop control — red X drawn like the chat image-thumb delete overlay."""
    btn = QPushButton(parent)
    btn.setToolTip("Stop generation")
    icon_px = _ICON_DISPLAY_PX
    color_pm = _chat_stop_icon_pixmap(size_px=icon_px)
    stop_icon = QIcon(color_pm)
    btn.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
    btn.setIcon(stop_icon)
    btn.setIconSize(QSize(icon_px, icon_px))
    btn.setFixedSize(_ICON_BTN_SIZE, _ICON_BTN_SIZE)
    btn.setStyleSheet(_icon_button_chrome_stylesheet())
    _ChatIconButtonHover(btn, stop_icon, stop_icon)
    btn.hide()
    return btn


def create_chat_favorite_button(parent=None):
    btn = QPushButton(parent)
    btn.setToolTip("Save as favorite user prompt")
    icon_px = _ICON_DISPLAY_PX
    normal_pm = _load_chat_asset_icon_pixmap(
        "chatfav.png", size_px=icon_px, matte_black=True
    )
    hover_pm = _load_chat_asset_icon_pixmap(
        "chatfav_hover.png", size_px=icon_px, matte_black=True
    )
    normal_icon = QIcon(normal_pm)
    hover_icon = QIcon(hover_pm if not hover_pm.isNull() else normal_pm)
    btn.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
    btn.setIcon(normal_icon)
    btn.setIconSize(QSize(icon_px, icon_px))
    btn.setFixedSize(_ICON_BTN_SIZE, _ICON_BTN_SIZE)
    btn.setStyleSheet(_icon_button_chrome_stylesheet())
    _ChatIconButtonHover(btn, normal_icon, hover_icon)
    return btn


def connect_chat_from_text_button_with_option_modifier(
    btn: QPushButton,
    on_click: Callable[..., None],
) -> None:
    """Wire from-text button; pass ``option_held=True`` when Option/Alt was down at press.

    ``QPushButton.clicked`` on macOS often runs after modifiers are cleared; read them
    from the press event instead (same pattern as option+click copy in EXIF editor).
    """

    def mouse_press(event):
        if event.button() == Qt.MouseButton.LeftButton:
            on_click(
                option_held=bool(
                    event.modifiers() & Qt.KeyboardModifier.AltModifier
                )
            )
            event.accept()
            return
        QPushButton.mousePressEvent(btn, event)

    btn.mousePressEvent = mouse_press


def chat_create_from_text_available() -> bool:
    try:
        from imagegen_plugins.image_gen_menu import imagegen_create_from_text_available

        return imagegen_create_from_text_available()
    except ImportError:
        return False
