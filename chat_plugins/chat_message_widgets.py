#!/usr/bin/env python3
"""Conversation message bubbles with edit / redo / delete controls."""

from __future__ import annotations

from typing import Callable, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import (
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from chat_plugins.chat_session import ChatMessage
from chat_plugins.chat_ui_common import (
    apply_chat_user_bubble_chrome,
    chat_assistant_message_stylesheet,
    chat_create_from_text_available,
    chat_prompt_edit_stylesheet,
    create_chat_delete_button,
    create_chat_edit_button,
    create_chat_from_text_button,
    create_chat_redo_button,
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
        self._body_label: _ChatMessageBodyLabel | None = None
        self._edit_input: QPlainTextEdit | None = None
        self._save_row_widget: QWidget | None = None

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

        if message.image_paths:
            from chat_plugins.chat_prompt_input import ChatImageThumbRow

            row = ChatImageThumbRow(
                self._bubble, compact_row=True, main_window=main_window
            )
            row.set_image_paths(message.image_paths, allow_remove=False)
            bubble_layout.addWidget(row)

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

        self._save_row_widget = QWidget(self._bubble)
        save_row = QHBoxLayout(self._save_row_widget)
        save_row.setContentsMargins(0, 0, 0, 0)
        save_row.setSpacing(4)
        save_btn = QPushButton("Save", self._save_row_widget)
        cancel_btn = QPushButton("Cancel", self._save_row_widget)
        save_btn.clicked.connect(self._commit_edit)
        cancel_btn.clicked.connect(self._cancel_edit)
        save_row.addStretch(1)
        save_row.addWidget(cancel_btn)
        save_row.addWidget(save_btn)
        self._save_row_widget.hide()
        bubble_layout.addWidget(self._save_row_widget)

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
        self._edit_input.setPlainText(self._message.text or "")
        self._edit_input.show()
        self._save_row_widget.show()
        self._edit_input.setFocus()

    def _commit_edit(self) -> None:
        if not self._editing or self._edit_input is None:
            return
        text = self._edit_input.toPlainText().strip()
        images = (
            list(self._message.image_paths)
            if self._message.role == "user"
            else []
        )
        self.edit_saved.emit(self._message.message_id, text, images)
        if self._editing:
            self._message.text = text
            self.finish_edit(self._message)

    def _teardown_edit_ui(self) -> None:
        if not self._editing:
            return
        if self._edit_input is not None:
            self._edit_input.hide()
        if self._save_row_widget is not None:
            self._save_row_widget.hide()
        if self._body_label is not None:
            self._body_label.show()
        self._editing = False

    def _cancel_edit(self) -> None:
        self._teardown_edit_ui()
        self._edit_btn.setEnabled(True)

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
