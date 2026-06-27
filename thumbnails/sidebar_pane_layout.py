#!/usr/bin/env python3
"""Shared splitter helpers for combined sidebar pane best-fit resize."""

from __future__ import annotations

MIN_PANE_CONTENT = 20


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
