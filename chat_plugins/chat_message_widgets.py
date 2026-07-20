#!/usr/bin/env python3
"""Conversation message bubbles with edit / redo / delete controls."""

from __future__ import annotations

from typing import Callable, Optional

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
    create_chat_favorite_button,
    connect_chat_from_text_button_with_option_modifier,
    create_chat_from_text_button,
    create_chat_redo_button,
    create_chat_stop_button,
    _icon_button_chrome_stylesheet,
    _local_paths_from_mime,
)
from theme.theme_service import get_active_theme


def _cmd_enter_pressed(event: QKeyEvent) -> bool:
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
        if self._message_widget._ignore_next_click_away_release:
            self._message_widget._ignore_next_click_away_release = False
            return False
        global_pos = event.globalPosition().toPoint()
        if not self._message_widget._point_in_edit_cell(global_pos):
            self._message_widget._commit_edit()
        return False


class ChatMessageWidget(QWidget):
    """One user or assistant message with action buttons."""

    edit_saved = Signal(str, str, list)
    edit_ended = Signal()
    redo_requested = Signal(str)
    delete_requested = Signal(str)
    create_from_text_requested = Signal(str, bool, list)
    favorite_requested = Signal(str)
    stop_requested = Signal()

    def __init__(
        self,
        message: ChatMessage,
        parent=None,
        *,
        on_edit_saved: Optional[Callable[[str, str, list], None]] = None,
        on_exclusive_edit_begin: Optional[Callable[["ChatMessageWidget"], None]] = None,
        on_redo: Optional[Callable[[str], None]] = None,
        on_delete: Optional[Callable[[str], None]] = None,
        on_create_from_text: Optional[Callable[[str, bool], None]] = None,
        on_favorite: Optional[Callable[[str], None]] = None,
        main_window=None,
    ):
        super().__init__(parent)
        self._message = message
        self._editing = False
        self._exclusive_edit_begin = on_exclusive_edit_begin
        self._suppress_edit_focus_out = False
        self._ignore_next_click_away_release = False
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

        self._thumb_row = None
        if message.role in ("user", "assistant"):
            self._thumb_row = ChatImageThumbRow(
                self._bubble, compact_row=True, main_window=main_window
            )
            self._thumb_row._allow_remove_when = lambda: self._editing
            bubble_layout.addWidget(self._thumb_row)
            self._bubble.setAcceptDrops(True)
            self._bubble.installEventFilter(self)
        self._sync_image_thumb_row()

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
        if message.role in ("user", "assistant"):
            self._body_label.setAcceptDrops(True)
            self._body_label.installEventFilter(self)
            if self._thumb_row is not None:
                self._thumb_row.installEventFilter(self)
                self._raise_image_thumb_row()

        self._edit_input = QPlainTextEdit(self._bubble)
        self._edit_input.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self._edit_input.setTabChangesFocus(False)
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
        self._stop_btn = None
        self._from_text_btn = None
        self._favorite_btn = None
        if message.role == "assistant" and chat_create_from_text_available():
            self._from_text_btn = create_chat_from_text_button(self)
            connect_chat_from_text_button_with_option_modifier(
                self._from_text_btn, self._on_create_from_text
            )
            if on_create_from_text is not None:
                self.create_from_text_requested.connect(on_create_from_text)
        if message.role == "user":
            self._stop_btn = create_chat_stop_button(self)
            self._stop_btn.clicked.connect(self.stop_requested.emit)
            self._favorite_btn = create_chat_favorite_button(self)
            self._favorite_btn.clicked.connect(
                lambda: self.favorite_requested.emit(message.message_id)
            )
            if on_favorite is not None:
                self.favorite_requested.connect(on_favorite)
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
        if self._favorite_btn is not None:
            if self._stop_btn is not None:
                actions.addWidget(self._stop_btn)
            actions.addWidget(self._favorite_btn)
        actions.addWidget(self._edit_btn)
        actions.addWidget(self._redo_btn)
        actions.addWidget(self._delete_btn)
        outer.addLayout(actions)
        self._sync_from_text_button()

    def message_id(self) -> str:
        return self._message.message_id

    def set_stop_visible(self, visible: bool) -> None:
        if self._stop_btn is not None:
            self._stop_btn.setVisible(visible)

    def displayed_image_paths(self) -> list[str]:
        if self._thumb_row is not None:
            paths = self._thumb_row.image_paths()
            if paths:
                return paths
        return list(self._message.image_paths or [])

    def _raise_image_thumb_row(self) -> None:
        if self._thumb_row is None:
            return
        self._thumb_row.raise_()
        if self._body_label is not None:
            self._body_label.stackUnder(self._thumb_row)

    def _sync_image_thumb_row(self, *, force: bool = False) -> None:
        if self._thumb_row is None:
            return
        paths = list(self._message.image_paths or [])
        if paths:
            allow_remove = self._message.role in ("user", "assistant") and self._editing
            self._thumb_row.set_image_paths(
                paths, allow_remove=allow_remove, force=force
            )
            self._thumb_row.show()
            self._raise_image_thumb_row()
        else:
            self._thumb_row.clear_images()
            self._thumb_row.hide()

    def is_editing(self) -> bool:
        return self._editing

    def _image_drop_targets(self) -> tuple[QWidget, ...]:
        if self._message.role not in ("user", "assistant"):
            return ()
        targets: list[QWidget] = []
        if self._bubble is not None:
            targets.append(self._bubble)
        if self._body_label is not None:
            targets.append(self._body_label)
        if self._thumb_row is not None:
            targets.append(self._thumb_row)
        return tuple(targets)

    def _arm_drop_click_away_suppression(self) -> None:
        """Ignore the mouse release that completes a drag-and-drop onto this message."""
        self._ignore_next_click_away_release = True

    def _handle_image_drop(self, paths: list[str]) -> bool:
        if self._message.role not in ("user", "assistant") or not paths:
            return False
        self._arm_drop_click_away_suppression()
        if not self._editing:
            if self._exclusive_edit_begin is not None:
                self._exclusive_edit_begin(self)
            else:
                self._enter_edit_mode()
        if self._thumb_row is not None:
            self._thumb_row.add_dropped_paths(paths)
        if self._editing and self._edit_input is not None:
            self._edit_input.setFocus()
        return True

    def _edit_cell_global_rects(self) -> list[QRect]:
        rects: list[QRect] = []
        if (
            self._message.role in ("user", "assistant")
            and self._editing
            and self._bubble is not None
        ):
            rects.append(
                QRect(self._bubble.mapToGlobal(QPoint(0, 0)), self._bubble.size())
            )
            return rects
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
        if watched in self._image_drop_targets():
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
                if isinstance(drop_event, QDropEvent):
                    paths = _local_paths_from_mime(drop_event.mimeData())
                    if paths and self._handle_image_drop(paths):
                        drop_event.acceptProposedAction()
                        return True
                    drop_event.ignore()
                    return True
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
                        self._arm_drop_click_away_suppression()
                        self._thumb_row.add_dropped_paths(paths)
                        if self._edit_input is not None:
                            self._edit_input.setFocus()
                        drop_event.acceptProposedAction()
                        return True
                    drop_event.ignore()
                    return True
            if event.type() == QEvent.Type.KeyPress and isinstance(event, QKeyEvent):
                if event.key() == Qt.Key.Key_Escape:
                    self._cancel_edit()
                    return True
                if _cmd_enter_pressed(event):
                    self._commit_edit()
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
        if self._ignore_next_click_away_release:
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

    def _on_create_from_text(self, *, option_held: bool = False) -> None:
        text = (self._message.text or "").strip()
        if not text:
            return
        source_paths = (
            self.displayed_image_paths()
            if self._message.role == "assistant"
            else []
        )
        self.create_from_text_requested.emit(text, option_held, source_paths)

    def _sync_from_text_button(self) -> None:
        if self._from_text_btn is None:
            return
        text = (self._message.text or "").strip()
        self._from_text_btn.setEnabled(bool(text))

    def update_message(self, message: ChatMessage) -> None:
        self._message = message
        if self._body_label is not None:
            self._body_label.setText(message.text or "")
        if not self._editing:
            self._sync_image_thumb_row()
        self._sync_from_text_button()

    def _start_edit(self) -> None:
        if self._editing:
            return
        if self._exclusive_edit_begin is not None:
            self._exclusive_edit_begin(self)
            return
        self._enter_edit_mode()

    def _enter_edit_mode(self) -> None:
        if self._editing:
            return
        self._editing = True
        self._edit_btn.setEnabled(False)
        if self._body_label is not None:
            self._body_label.hide()
        if self._thumb_row is not None and self._message.role in ("user", "assistant"):
            self._thumb_row.set_image_paths(
                list(self._message.image_paths or []), allow_remove=True
            )
            self._raise_image_thumb_row()
        self._edit_input.setPlainText(self._message.text or "")
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
                if self._thumb_row is not None
                and self._message.role in ("user", "assistant")
                else []
            )
            self.edit_saved.emit(self._message.message_id, text, images)
            if self._editing:
                self.finish_edit()
        finally:
            self._suppress_edit_focus_out = False

    def _teardown_edit_ui(self) -> None:
        if not self._editing:
            return
        self._detach_click_away_filter()
        if self._edit_input is not None:
            self._edit_input.hide()
        self._editing = False
        if self._thumb_row is not None:
            self._sync_image_thumb_row(force=True)
        if self._body_label is not None:
            self._body_label.setText(self._message.text or "")
            self._body_label.show()
        self._edit_btn.setEnabled(True)
        self.edit_ended.emit()

    def _cancel_edit(self) -> None:
        self._suppress_edit_focus_out = True
        try:
            self._teardown_edit_ui()
        finally:
            self._suppress_edit_focus_out = False

    def finish_edit(self) -> None:
        """Leave edit mode; message content is refreshed by the pane on save."""
        self._cancel_edit()

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
        action_ss = _icon_button_chrome_stylesheet()
        for btn in (
            self._edit_btn,
            self._redo_btn,
            self._delete_btn,
            self._from_text_btn,
            self._favorite_btn,
            self._stop_btn,
        ):
            if btn is not None:
                btn.setStyleSheet(action_ss)
