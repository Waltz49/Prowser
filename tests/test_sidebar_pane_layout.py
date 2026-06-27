"""Tests for shared sidebar splitter helpers."""

from thumbnails.sidebar_pane_layout import (
    MIN_PREVIEW_CONTENT_HEIGHT,
    apply_pane_titlebar_drag_delta,
    pane_fit_height_tolerance,
    pane_height_at_target,
    pane_min_height,
)


class _FakeSplitter:
    def __init__(self, sizes: list[int]):
        self._sizes = list(sizes)

    def sizes(self) -> list[int]:
        return list(self._sizes)

    def setSizes(self, sizes: list[int]) -> None:
        self._sizes = list(sizes)


def _min_h_factory(mins: dict[int, int]):
    def min_height_for_pane(idx: int, *, header_only: bool = False) -> int:
        if header_only:
            return mins.get(idx, 30)
        return mins.get(idx, 50)

    return min_height_for_pane


def test_pane_min_height_defaults():
    assert pane_min_height(30) == 50
    assert pane_min_height(30, header_only=True) == 30


def test_titlebar_drag_down_shrinks_lower_pane_only():
    splitter = _FakeSplitter([100, 200, 80])
    vis = [True, True, True]
    min_h = _min_h_factory({0: 50, 1: 50, 2: 50})

    assert apply_pane_titlebar_drag_delta(
        splitter, 2, 20, vis, min_h, start_sizes=[100, 200, 80]
    )
    assert splitter._sizes == [100, 220, 60]


def test_titlebar_drag_up_grows_lower_pane():
    splitter = _FakeSplitter([100, 200, 80])
    vis = [True, True, True]
    min_h = _min_h_factory({0: 50, 1: 50, 2: 50})

    assert apply_pane_titlebar_drag_delta(
        splitter, 2, -20, vis, min_h, start_sizes=[100, 200, 80]
    )
    assert splitter._sizes == [100, 180, 100]


def test_titlebar_drag_clamps_at_minimum():
    splitter = _FakeSplitter([100, 200, 55])
    vis = [True, True, True]
    min_h = _min_h_factory({0: 50, 1: 50, 2: 50})

    assert apply_pane_titlebar_drag_delta(
        splitter, 2, 20, vis, min_h, start_sizes=[100, 200, 55]
    )
    assert splitter._sizes == [100, 205, 50]


def test_titlebar_drag_uses_start_sizes_not_current():
    splitter = _FakeSplitter([100, 200, 80])
    vis = [True, True, True]
    min_h = _min_h_factory({0: 50, 1: 50, 2: 50})

    apply_pane_titlebar_drag_delta(
        splitter, 2, 10, vis, min_h, start_sizes=[100, 200, 80]
    )
    assert apply_pane_titlebar_drag_delta(
        splitter, 2, 20, vis, min_h, start_sizes=[100, 200, 80]
    )
    assert splitter._sizes == [100, 220, 60]


def test_preview_content_constant():
    assert MIN_PREVIEW_CONTENT_HEIGHT == 64


def test_pane_height_at_target_uses_tolerance():
    assert pane_height_at_target(400, 405)
    assert pane_height_at_target(400, 420) is False
    assert pane_height_at_target(400, 500, stored_target=402)


def test_pane_fit_height_tolerance_scales():
    assert pane_fit_height_tolerance(100) == 8
    assert pane_fit_height_tolerance(1000) == 20
