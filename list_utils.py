#!/usr/bin/env python3
"""Small list helpers used across the app."""

from typing import Iterable, List, TypeVar

T = TypeVar("T")


def dedupe_preserve_order(items: Iterable[T]) -> List[T]:
    """Remove duplicates while preserving first-seen order."""
    seen: set = set()
    unique: List[T] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            unique.append(item)
    return unique
