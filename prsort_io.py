#!/usr/bin/env python3
"""Shared .prsort file parsing (custom sort order and lock markers)."""

from typing import List, Optional, Set, Tuple

LOCK_PREFIX = "*"

# Warning header lines written by the app; readers must skip them.
_PRSORT_WARNING_PREFIXES = (
    "# THIS FILE IS ONLY FOR",
    "# THIS FILE MUST NOT BE USED",
)
_PRSORT_DO_NOT_USE_PREFIX = "# DO NOT USE"


def strip_prsort_warning_lines(lines: List[str]) -> List[str]:
    """Remove leading warning comment lines from stripped .prsort lines."""
    if not lines:
        return lines
    if lines[0].startswith(_PRSORT_WARNING_PREFIXES):
        lines = lines[1:]
        if lines and lines[0].startswith(_PRSORT_DO_NOT_USE_PREFIX):
            lines = lines[1:]
    return lines


def read_prsort_lines(path: str) -> Optional[List[str]]:
    """Read non-empty stripped lines from a .prsort file, or None on failure."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            lines = [line.strip() for line in f if line.strip()]
        if not lines:
            return None
        return strip_prsort_warning_lines(lines)
    except OSError:
        return None


def parse_locked_filenames(lines: List[str]) -> Set[str]:
    """
    Parse lock markers from .prsort body lines (after optional #reversed: header).

    Lines starting with '*' are locked; returns basenames without the prefix.
    """
    locked: Set[str] = set()
    start_idx = 1 if lines and lines[0].startswith("#reversed:") else 0
    for line in lines[start_idx:]:
        if line.startswith(LOCK_PREFIX):
            locked.add(line[1:])
    return locked


def parse_custom_sort_file(
    lines: List[str],
) -> Optional[Tuple[List[str], bool, Set[str]]]:
    """
    Parse a full custom-sort .prsort file.

    Returns (ordered_filenames, is_reversed, locked_filenames) or None if invalid.
    Requires a #reversed: header as first line after warnings.
    """
    if not lines:
        return None
    first_line = lines[0]
    if not first_line.startswith("#reversed:"):
        return None
    is_reversed_str = first_line.split(":", 1)[1].lower()
    is_reversed = is_reversed_str == "true"
    body = lines[1:]
    cleaned: List[str] = []
    locked: Set[str] = set()
    for line in body:
        if line.startswith(LOCK_PREFIX):
            filename = line[1:]
            cleaned.append(filename)
            locked.add(filename)
        else:
            cleaned.append(line)
    return (cleaned, is_reversed, locked)
