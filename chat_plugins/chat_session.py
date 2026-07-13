#!/usr/bin/env python3
"""In-memory chat session state for the sidebar chat pane."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Literal, Optional

ChatRole = Literal["user", "assistant"]
ImageGenAutoMode = Literal["create", "edit"]


@dataclass
class ChatMessage:
    role: ChatRole
    text: str
    message_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    image_paths: list[str] = field(default_factory=list)
    source_image_paths: list[str] = field(default_factory=list)
    image_gen_auto: Optional[ImageGenAutoMode] = None


class ChatSession:
    """Session-scoped conversation history.

    Messages are cleared on Clear Chat. When preserve-across-sessions is enabled,
    messages are also saved under the profile data directory.
    ``system_prompt`` is initialized from persisted settings and kept for the session.
    """

    def __init__(self, system_prompt: str = "") -> None:
        self.messages: list[ChatMessage] = []
        self.system_prompt: str = system_prompt

    def clear(self) -> None:
        self.messages.clear()

    def append(self, message: ChatMessage) -> None:
        self.messages.append(message)

    def message_at(self, index: int) -> ChatMessage | None:
        if 0 <= index < len(self.messages):
            return self.messages[index]
        return None

    def index_of(self, message_id: str) -> int:
        for idx, msg in enumerate(self.messages):
            if msg.message_id == message_id:
                return idx
        return -1

    def remove_at(self, index: int) -> ChatMessage | None:
        if 0 <= index < len(self.messages):
            return self.messages.pop(index)
        return None

    def truncate_after(self, index: int) -> None:
        """Keep messages through *index* inclusive."""
        if index < 0:
            self.messages.clear()
            return
        self.messages = self.messages[: index + 1]

    def last_user_index(self) -> int:
        for idx in range(len(self.messages) - 1, -1, -1):
            if self.messages[idx].role == "user":
                return idx
        return -1

    def user_index_for_redo(self, message_id: str) -> int:
        """User message to keep when redoing *message_id* (that user or its assistant reply)."""
        idx = self.index_of(message_id)
        if idx < 0:
            return -1
        if self.messages[idx].role == "user":
            return idx
        for i in range(idx - 1, -1, -1):
            if self.messages[i].role == "user":
                return i
        return -1

    def has_started(self) -> bool:
        return bool(self.messages)
