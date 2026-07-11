#!/usr/bin/env python3
"""Conversation message bubbles with edit / redo / delete controls."""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QEvent, QObject, QPoint, QRect, Qt, QTimer, Signal
from PySide6.QtGui import QCursor, QDragEnterEvent, QDragMoveEvent, QDropEvent, QKeyEvent, QMouseEvent
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from chat_plugins.chat_session import ChatMessage
from chat_plugins.chat_ui_common import (
    ChatImageThumbRow,
    apply_chat_user_bubble_chrome,
    chat_assistant_message_stylesheet,
    chat_create_from_text_available,
    chat_prompt_edit_stylesheet,
    create_chat_delete_button,
    create_chat_edit_button,
    create_chat_from_text_button,
    create_chat_redo_button,
    _local_paths_from_mime,
)
from theme.theme_service import get_active_theme


class _ChatMessageBodyLabel(QLabel):
    """Message text; double-click opens inline edit (same as the edit button)."""

    edit_requested = Signal()

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.edit_requested.emit()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)


class _EditClickAwayFilter(QObject):
    """Commit inline edit when the user releases a click outside the edit cell."""

    def __init__(self, message_widget: "ChatMessageWidget") -> None:
        super().__init__(message_widget)
        self._message_widget = message_widget

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        del watched
        if not self._message_widget._editing:
            return False
        if not isinstance(event, QMouseEvent):
            return False
        if event.type() != QEvent.Type.MouseButtonRelease:
            return False
        if event.button() != Qt.MouseButton.LeftButton:
            return False
        global_pos = event.globalPosition().toPoint()
        if not self._message_widget._point_in_edit_cell(global_pos):
            self._message_widget._commit_edit()
        return False


class ChatMessageWidget(QWidget):
    """One user or assistant message with action buttons."""

    edit_saved = Signal(str, str, list)
    redo_requested = Signal(str)
    delete_requested = Signal(str)
    create_from_text_requested = Signal(str)

    def __init__(
        self,
        message: ChatMessage,
        parent=None,
        *,
        on_edit_saved: Optional[Callable[[str, str, list], None]] = None,
        on_redo: Optional[Callable[[str], None]] = None,
        on_delete: Optional[Callable[[str], None]] = None,
        on_create_from_text: Optional[Callable[[str], None]] = None,
        main_window=None,
    ):
        super().__init__(parent)
        self._message = message
        self._editing = False
        self._suppress_edit_focus_out = False
        self._click_away_filter: _EditClickAwayFilter | None = None
        self._body_label: _ChatMessageBodyLabel | None = None
        self._edit_input: QPlainTextEdit | None = None
        self._thumb_row: ChatImageThumbRow | None = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(6, 4, 6, 4)
        outer.setSpacing(4)

        if message.role == "user":
            self._bubble = QGroupBox(self)
            self._bubble.setObjectName("chatUserBubble")
            apply_chat_user_bubble_chrome(self._bubble)
        else:
            self._bubble = QFrame(self)
            self._bubble.setObjectName("chatAssistantBubble")
            self._bubble.setStyleSheet(chat_assistant_message_stylesheet())
        bubble_layout = QVBoxLayout(self._bubble)
        bubble_layout.setContentsMargins(8, 8, 8, 8)
        bubble_layout.setSpacing(6)

        if message.role == "user":
            self._thumb_row = ChatImageThumbRow(
                self._bubble, compact_row=True, main_window=main_window
            )
            self._thumb_row._allow_remove_when = lambda: self._editing
            if message.image_paths:
                self._thumb_row.set_image_paths(
                    message.image_paths, allow_remove=False
                )
            else:
                self._thumb_row.hide()
            bubble_layout.addWidget(self._thumb_row)

        self._body_label = _ChatMessageBodyLabel(message.text, self._bubble)
        self._body_label.edit_requested.connect(self._start_edit)
        self._body_label.setWordWrap(True)
        self._body_label.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop
        )
        self._body_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        th = get_active_theme()
        self._body_label.setStyleSheet(
            f"color: {th.dialog_text_color_hex}; background-color: transparent;"
        )
        bubble_layout.addWidget(self._body_label)

        self._edit_input = QPlainTextEdit(self._bubble)
        self._edit_input.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self._edit_input.setStyleSheet(chat_prompt_edit_stylesheet())
        self._edit_input.setMinimumHeight(72)
        self._edit_input.setMaximumHeight(180)
        self._edit_input.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        self._edit_input.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        self._edit_input.hide()
        bubble_layout.addWidget(self._edit_input)
        self._edit_input.installEventFilter(self)
        self._edit_input.setAcceptDrops(True)

        self._bubble.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
        outer.addWidget(self._bubble)

        actions = QHBoxLayout()
        actions.setContentsMargins(4, 0, 4, 0)
        actions.setSpacing(4)
        self._from_text_btn = None
        if message.role == "assistant" and chat_create_from_text_available():
            self._from_text_btn = create_chat_from_text_button(self)
            self._from_text_btn.clicked.connect(self._on_create_from_text)
            if on_create_from_text is not None:
                self.create_from_text_requested.connect(on_create_from_text)
        self._edit_btn = create_chat_edit_button(self)
        self._redo_btn = create_chat_redo_button(self)
        self._delete_btn = create_chat_delete_button(self)
        self._edit_btn.clicked.connect(self._start_edit)
        self._redo_btn.clicked.connect(lambda: self.redo_requested.emit(message.message_id))
        self._delete_btn.clicked.connect(
            lambda: self.delete_requested.emit(message.message_id)
        )
        if on_edit_saved is not None:
            self.edit_saved.connect(on_edit_saved)
        if on_redo is not None:
            self.redo_requested.connect(on_redo)
        if on_delete is not None:
            self.delete_requested.connect(on_delete)
        actions.addStretch(1)
        if self._from_text_btn is not None:
            actions.addWidget(self._from_text_btn)
        actions.addWidget(self._edit_btn)
        actions.addWidget(self._redo_btn)
        actions.addWidget(self._delete_btn)
        outer.addLayout(actions)
        self._sync_from_text_button()

    def message_id(self) -> str:
        return self._message.message_id

    def _edit_cell_global_rects(self) -> list[QRect]:
        rects: list[QRect] = []
        if self._edit_input is not None and self._edit_input.isVisible():
            rects.append(
                QRect(self._edit_input.mapToGlobal(QPoint(0, 0)), self._edit_input.size())
            )
        if self._thumb_row is not None and self._thumb_row.isVisible():
            rects.append(
                QRect(self._thumb_row.mapToGlobal(QPoint(0, 0)), self._thumb_row.size())
            )
        return rects

    def _point_in_edit_cell(self, global_pos: QPoint) -> bool:
        for rect in self._edit_cell_global_rects():
            if rect.contains(global_pos):
                return True
        return False

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if watched is self._edit_input and self._editing:
            if event.type() in (
                QEvent.Type.DragEnter,
                QEvent.Type.DragMove,
            ):
                drag_event = event
                if isinstance(drag_event, (QDragEnterEvent, QDragMoveEvent)):
                    if _local_paths_from_mime(drag_event.mimeData()):
                        drag_event.acceptProposedAction()
                        return True
                    drag_event.ignore()
                    return True
            if event.type() == QEvent.Type.Drop:
                drop_event = event
                if isinstance(drop_event, QDropEvent) and self._thumb_row is not None:
                    paths = _local_paths_from_mime(drop_event.mimeData())
                    if paths:
                        self._thumb_row.add_dropped_paths(paths)
                        drop_event.acceptProposedAction()
                        return True
                    drop_event.ignore()
                    return True
            if event.type() == QEvent.Type.KeyPress and isinstance(event, QKeyEvent):
                if event.key() == Qt.Key.Key_Escape:
                    self._cancel_edit()
                    return True
            if event.type() == QEvent.Type.FocusOut:
                QTimer.singleShot(0, self._commit_edit_if_focus_left)
        return super().eventFilter(watched, event)

    def _focus_left_edit_entry(self) -> bool:
        focus = QApplication.focusWidget()
        if focus is not None:
            if self._edit_input is not None and (
                focus is self._edit_input or self._edit_input.isAncestorOf(focus)
            ):
                return False
            if self._thumb_row is not None and (
                focus is self._thumb_row or self._thumb_row.isAncestorOf(focus)
            ):
                return False
            return True
        global_pos = QCursor.pos()
        return not self._point_in_edit_cell(global_pos)

    def _commit_edit_if_focus_left(self) -> None:
        if not self._editing or self._suppress_edit_focus_out:
            return
        if QApplication.mouseButtons() & Qt.MouseButton.LeftButton:
            return
        if self._focus_left_edit_entry():
            self._commit_edit()

    def _attach_click_away_filter(self) -> None:
        if self._click_away_filter is not None:
            return
        self._click_away_filter = _EditClickAwayFilter(self)
        app = QApplication.instance()
        if app is not None:
            app.installEventFilter(self._click_away_filter)

    def _detach_click_away_filter(self) -> None:
        if self._click_away_filter is None:
            return
        app = QApplication.instance()
        if app is not None:
            app.removeEventFilter(self._click_away_filter)
        self._click_away_filter = None

    def _on_create_from_text(self) -> None:
        text = (self._message.text or "").strip()
        if not text:
            return
        self.create_from_text_requested.emit(text)

    def _sync_from_text_button(self) -> None:
        if self._from_text_btn is None:
            return
        text = (self._message.text or "").strip()
        self._from_text_btn.setEnabled(bool(text))

    def update_message(self, message: ChatMessage) -> None:
        self._message = message
        if not self._editing and self._body_label is not None:
            self._body_label.setText(message.text)
        self._sync_from_text_button()

    def _start_edit(self) -> None:
        if self._editing:
            return
        self._editing = True
        self._edit_btn.setEnabled(False)
        if self._body_label is not None:
            self._body_label.hide()
        if self._thumb_row is not None and self._message.role == "user":
            self._thumb_row.set_image_paths(
                self._message.image_paths, allow_remove=True
            )
            self._thumb_row.refresh_hover_under_cursor()
        self._edit_input.setPlainText(self._message.text or "")
        self._edit_input.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._edit_input.show()
        self._attach_click_away_filter()
        self._edit_input.setFocus()

    def _commit_edit(self) -> None:
        if not self._editing or self._edit_input is None:
            return
        self._suppress_edit_focus_out = True
        try:
            text = self._edit_input.toPlainText().strip()
            images = (
                self._thumb_row.image_paths()
                if self._thumb_row is not None and self._message.role == "user"
                else []
            )
            self.edit_saved.emit(self._message.message_id, text, images)
            if self._editing:
                self._message.text = text
                self.finish_edit(self._message)
        finally:
            self._suppress_edit_focus_out = False

    def _teardown_edit_ui(self) -> None:
        if not self._editing:
            return
        self._detach_click_away_filter()
        if self._edit_input is not None:
            self._edit_input.hide()
        if self._thumb_row is not None:
            if self._message.image_paths:
                self._thumb_row.set_image_paths(
                    self._message.image_paths, allow_remove=False
                )
            else:
                self._thumb_row.clear_images()
                self._thumb_row.hide()
        if self._body_label is not None:
            self._body_label.show()
        self._editing = False

    def _cancel_edit(self) -> None:
        self._suppress_edit_focus_out = True
        try:
            self._teardown_edit_ui()
            self._edit_btn.setEnabled(True)
        finally:
            self._suppress_edit_focus_out = False

    def finish_edit(self, message: ChatMessage | None = None) -> None:
        """Leave edit mode and optionally refresh displayed message text."""
        self._cancel_edit()
        if message is not None:
            self.update_message(message)

    def refresh_theme_styles(self) -> None:
        if self._message.role == "user":
            apply_chat_user_bubble_chrome(self._bubble)
        elif isinstance(self._bubble, QFrame):
            self._bubble.setStyleSheet(chat_assistant_message_stylesheet())
        if self._body_label is not None:
            th = get_active_theme()
            self._body_label.setStyleSheet(
                f"color: {th.dialog_text_color_hex}; background-color: transparent;"
            )
        if self._edit_input is not None:
            self._edit_input.setStyleSheet(chat_prompt_edit_stylesheet())
