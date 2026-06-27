#!/usr/bin/env python3
"""Shared splitter helpers for combined sidebar pane best-fit resize."""

from __future__ import annotations

MIN_PANE_CONTENT = 20
MIN_PREVIEW_CONTENT_HEIGHT = 64
MIN_INFORMATION_CONTENT_HEIGHT = 20
MIN_JOBS_QUEUE_CONTENT_HEIGHT = 20

# Tolerance for "already fit to content" double-click toggle (px).
PANE_FIT_HEIGHT_TOLERANCE_MIN = 8


def pane_fit_height_tolerance(needed: int) -> int:
    """Pixel slack when comparing splitter size to a fit-to-content target."""
    if needed <= 0:
        return PANE_FIT_HEIGHT_TOLERANCE_MIN
    return max(PANE_FIT_HEIGHT_TOLERANCE_MIN, int(needed * 0.02))


def pane_height_at_target(
    current: int,
    needed: int,
    *,
    stored_target: int | None = None,
) -> bool:
    """True when *current* splitter size matches a fit-to-content target."""
    if needed <= 0 and stored_target is None:
        return False
    ref = needed if needed > 0 else (stored_target or 0)
    if ref <= 0:
        return False
    tolerance = pane_fit_height_tolerance(ref)
    if stored_target is not None and abs(current - stored_target) <= tolerance:
        return True
    return abs(current - needed) <= tolerance


def pane_min_height(header_h: int, *, header_only: bool = False) -> int:
    if header_only:
        return header_h
    return header_h + MIN_PANE_CONTENT


def collapse_order(target_idx: int, other_indices: list[int]) -> list[int]:
    """Order to shrink other panes: below target first, then above."""
    below = sorted((i for i in other_indices if i > target_idx), reverse=True)
    above = sorted((i for i in other_indices if i < target_idx), reverse=True)
    return below + above


def collapse_flags_for_target(
    target_idx: int,
    needed_target: int,
    total: int,
    vis: list[bool],
    min_height_for_pane,
) -> dict[int, bool]:
    """Decide which other panes shrink to header-only so *needed_target* can fit."""
    other_indices = [i for i, v in enumerate(vis) if v and i != target_idx]
    other_mins = {i: min_height_for_pane(i, header_only=False) for i in other_indices}
    flags: dict[int, bool] = {}
    max_target = total - sum(other_mins.values())
    if needed_target <= max_target:
        return flags
    for i in collapse_order(target_idx, other_indices):
        flags[i] = True
        other_mins[i] = min_height_for_pane(i, header_only=True)
        max_target = total - sum(other_mins.values())
        if needed_target <= max_target:
            break
    return flags


def redistribute_for_target_pane(
    splitter,
    pane_count: int,
    target_idx: int,
    needed_target: int,
    vis: list[bool],
    header_height_for_pane,
    min_height_for_pane,
    total_height: int,
    *,
    collapse_header_only: dict[int, bool] | None = None,
) -> list[int]:
    """Resize the target pane to *needed_target*; shrink others proportionally."""
    collapse_header_only = collapse_header_only or {}
    if not vis[target_idx]:
        return list(splitter.sizes())

    total = max(total_height, 1)
    other_indices = [i for i, v in enumerate(vis) if v and i != target_idx]
    target_header = header_height_for_pane(target_idx)
    needed_target = max(needed_target, pane_min_height(target_header))

    other_mins: dict[int, int] = {}
    for i in other_indices:
        header_only = collapse_header_only.get(i, False)
        other_mins[i] = min_height_for_pane(i, header_only=header_only)

    max_target = total - sum(other_mins.values())
    new_target = min(needed_target, max(max_target, pane_min_height(target_header)))

    sizes = list(splitter.sizes())
    if len(sizes) < pane_count:
        sizes.extend([0] * (pane_count - len(sizes)))

    new_sizes = [0] * pane_count
    if not other_indices:
        new_sizes[target_idx] = min(needed_target, total)
    else:
        new_sizes[target_idx] = new_target
        remainder = total - new_target
        other_total = sum(sizes[i] for i in other_indices)
        if other_total > 0:
            for i in other_indices:
                new_sizes[i] = max(
                    other_mins[i], int(remainder * sizes[i] / other_total)
                )
        else:
            each = remainder // len(other_indices)
            for i in other_indices:
                new_sizes[i] = max(other_mins[i], each)
        drift = total - sum(new_sizes)
        if drift:
            adjust = max(other_indices, key=lambda j: new_sizes[j])
            new_sizes[adjust] = max(other_mins[adjust], new_sizes[adjust] + drift)
    return new_sizes


def ensure_pane_headers_visible(
    splitter,
    vis: list[bool],
    min_height_for_pane,
    *,
    collapse_header_only: dict[int, bool] | None = None,
) -> list[int] | None:
    """Return adjusted sizes when a visible pane is shorter than its title bar."""
    collapse_header_only = collapse_header_only or {}
    visible = [i for i, v in enumerate(vis) if v]
    if len(visible) <= 1:
        return None

    sizes = list(splitter.sizes())
    total = sum(sizes)
    if total <= 0:
        return None

    mins: list[int] = []
    for i, shown in enumerate(vis):
        if not shown:
            mins.append(0)
        elif collapse_header_only.get(i, False):
            mins.append(min_height_for_pane(i, header_only=True))
        else:
            mins.append(min_height_for_pane(i))

    deficit = 0
    for i in visible:
        if sizes[i] < mins[i]:
            deficit += mins[i] - sizes[i]
            sizes[i] = mins[i]

    if deficit <= 0:
        return None

    donors = sorted(
        [i for i in visible if sizes[i] > mins[i]],
        key=lambda i: sizes[i] - mins[i],
        reverse=True,
    )
    for i in donors:
        if deficit <= 0:
            break
        take = min(sizes[i] - mins[i], deficit)
        sizes[i] -= take
        deficit -= take

    drift = total - sum(sizes)
    if drift and donors:
        sizes[donors[0]] += drift
    return sizes


def apply_pane_titlebar_drag_delta(
    splitter,
    pane_idx: int,
    dy: int,
    vis: list[bool],
    min_height_for_pane,
    *,
    start_sizes: list[int] | None = None,
) -> bool:
    """Move pane *pane_idx*'s title bar by *dy* screen pixels (cursor-following)."""
    if pane_idx < 1 or dy == 0:
        return False
    if pane_idx >= len(vis) or not vis[pane_idx]:
        return False
    upper = pane_idx - 1
    if not vis[upper]:
        return False

    base = list(start_sizes if start_sizes is not None else splitter.sizes())
    if len(base) <= pane_idx:
        return False

    min_upper = min_height_for_pane(upper)
    min_lower = min_height_for_pane(pane_idx)
    # Drag down: title bar moves down => neighbor above grows, this pane shrinks.
    if dy > 0:
        dy = min(dy, max(0, base[pane_idx] - min_lower))
    else:
        dy = max(dy, -max(0, base[upper] - min_upper))
    if dy == 0:
        return False

    sizes = list(base)
    sizes[upper] = base[upper] + dy
    sizes[pane_idx] = base[pane_idx] - dy
    splitter.setSizes(sizes)
    return True
