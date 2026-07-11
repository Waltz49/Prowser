#!/usr/bin/env python3
"""Detect /image slash commands in chat user messages."""

from __future__ import annotations

import re
from typing import Literal, Optional

ImageGenChatCommand = Literal["create", "edit"]

# Prefixes of "image" with the full token at least 3 characters (/im … /image).
# (?<!\w) allows a match at the start of the message (``\b`` alone does not).
_IMAGE_COMMAND_RE = re.compile(
    r"(?<!\w)/(?:im|ima|imag|image)\b",
    re.IGNORECASE,
)


def user_message_has_image_command(text: str) -> bool:
    """True when *text* contains a separate /image abbreviation word."""
    return bool(_IMAGE_COMMAND_RE.search(text or ""))


def classify_user_message_image_gen_command(
    text: str,
    *,
    has_user_images: bool,
) -> Optional[ImageGenChatCommand]:
    """Return auto image-gen mode for a user message, or None when no /image command."""
    if not user_message_has_image_command(text):
        return None
    return "edit" if has_user_images else "create"


def strip_image_gen_commands_from_user_message(text: str) -> str:
    """Remove /image command tokens from *text* (for LM Studio payloads)."""
    stripped = _IMAGE_COMMAND_RE.sub("", text or "")
    stripped = re.sub(r"[ \t]{2,}", " ", stripped)
    return stripped.strip()


def prepare_user_message_for_storage(
    text: str,
    image_paths: list[str],
    main_window,
) -> tuple[str, list[str], Optional[ImageGenChatCommand]]:
    """Apply ``{}`` trigger and record auto image-gen intent; keep ``/image`` in *text*."""
    from chat_plugins.chat_selection_image_trigger import apply_selection_image_trigger

    text, image_paths = apply_selection_image_trigger(
        text, image_paths, main_window
    )
    mode = classify_user_message_image_gen_command(
        text,
        has_user_images=bool(image_paths),
    )
    return text, image_paths, mode
