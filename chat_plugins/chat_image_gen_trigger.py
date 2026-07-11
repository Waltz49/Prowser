#!/usr/bin/env python3
"""Detect /image-style slash commands in chat user messages."""

from __future__ import annotations

import re

# Prefixes of "image" with the full token at least 3 characters (/im … /image).
# (?<!\w) allows a match at the start of the message (``\b`` alone does not).
_IMAGE_COMMAND_RE = re.compile(
    r"(?<!\w)/(?:im|ima|imag|image)\b",
    re.IGNORECASE,
)


def user_message_has_image_command(text: str) -> bool:
    """True when *text* contains a separate /image abbreviation word."""
    return bool(_IMAGE_COMMAND_RE.search(text or ""))


def strip_image_command_from_user_message(text: str) -> str:
    """Remove /image-style command tokens from *text* (for LM Studio payloads)."""
    stripped = _IMAGE_COMMAND_RE.sub("", text or "")
    stripped = re.sub(r"[ \t]{2,}", " ", stripped)
    return stripped.strip()
