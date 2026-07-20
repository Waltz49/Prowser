#!/usr/bin/env python3
"""Detect /create and /source slash commands in chat user messages."""

from __future__ import annotations

import re
from typing import Literal, Optional

ImageGenChatCommand = Literal["create", "edit"]

# Prefixes of "create" (min /cr) and legacy /image for saved chats.
_CREATE_COMMAND_RE = re.compile(
    r"(?<!\w)/(?:cr|cre|crea|creat|create|im|ima|imag|image)\b",
    re.IGNORECASE,
)

# Prefixes of "source" and /src (/so … /source).
_SOURCE_COMMAND_RE = re.compile(
    r"(?<!\w)/(?:so|sou|sour|sourc|source|src)\b",
    re.IGNORECASE,
)

_CHAT_TRIGGER_RE = re.compile(
    r"(?<!\w)/(?:"
    r"cr|cre|crea|creat|create|im|ima|imag|image|"
    r"so|sou|sour|sourc|source|src"
    r")\b",
    re.IGNORECASE,
)


def user_message_has_create_command(text: str) -> bool:
    """True when *text* contains a /create (or legacy /image) abbreviation."""
    return bool(_CREATE_COMMAND_RE.search(text or ""))


def user_message_has_source_command(text: str) -> bool:
    """True when *text* contains a /source (/src, /so, …) abbreviation."""
    return bool(_SOURCE_COMMAND_RE.search(text or ""))


def user_message_has_image_command(text: str) -> bool:
    """Backward-compatible alias for create-command detection."""
    return user_message_has_create_command(text)


def classify_user_message_image_gen_command(
    text: str,
    *,
    has_user_images: bool,
) -> Optional[ImageGenChatCommand]:
    """Return auto image-gen mode for /create, or None when no create command."""
    if not user_message_has_create_command(text):
        return None
    return "edit" if has_user_images else "create"


def user_message_wants_assistant_sources(
    text: str,
    *,
    has_user_images: bool,
) -> bool:
    """True when /source should copy reference images onto the assistant reply."""
    return bool(has_user_images and user_message_has_source_command(text))


def strip_create_commands_from_user_message(text: str) -> str:
    """Remove /create command tokens from *text* (not /source)."""
    stripped = _CREATE_COMMAND_RE.sub("", text or "")
    stripped = re.sub(r"[ \t]{2,}", " ", stripped)
    return stripped.strip()


def strip_image_gen_commands_from_user_message(text: str) -> str:
    """Remove /create and /source command tokens from *text* (for LM Studio payloads)."""
    stripped = _CHAT_TRIGGER_RE.sub("", text or "")
    stripped = re.sub(r"[ \t]{2,}", " ", stripped)
    return stripped.strip()


def effective_image_gen_auto_mode(
    text: str,
    *,
    has_user_images: bool,
    automatic_create: bool = False,
) -> Optional[ImageGenChatCommand]:
    """Resolve auto image-gen mode from the live setting or explicit slash commands."""
    if automatic_create:
        return "edit" if has_user_images else "create"
    return classify_user_message_image_gen_command(
        text,
        has_user_images=has_user_images,
    )


def prepare_user_message_for_storage(
    text: str,
    image_paths: list[str],
    main_window,
    *,
    automatic_create: bool = False,
    keep_selection_trigger: bool = False,
) -> tuple[str, list[str], Optional[ImageGenChatCommand]]:
    """Apply ``{}`` trigger and record auto image-gen intent; keep slash commands in *text*."""
    from chat_plugins.chat_selection_image_trigger import apply_selection_image_trigger

    text, image_paths = apply_selection_image_trigger(
        text,
        image_paths,
        main_window,
        keep_trigger_in_text=keep_selection_trigger,
    )
    if automatic_create:
        text = strip_create_commands_from_user_message(text)
        mode: Optional[ImageGenChatCommand] = (
            "edit" if image_paths else "create"
        )
    else:
        mode = classify_user_message_image_gen_command(
            text,
            has_user_images=bool(image_paths),
        )
    return text, image_paths, mode
