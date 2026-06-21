#!/usr/bin/env python3
"""Layered DAG layout and spline edge routing for reference dependency graphs."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

from PySide6.QtCore import QPointF, QRect

from search.reference_graph import ReferenceGraph
from thumbnails.thumbnail_constants import (
    BASE_MARGIN,
    BORDER_SPACE,
    CANVAS_TOTAL_BOTTOM_MARGIN,
    CANVAS_TOTAL_TOP_MARGIN,
    THUMBNAIL_SPACING,
)


def _norm_path(path: str) -> str:
    return os.path.normpath(os.path.abspath(path))


# Reference-graph edge strokes: ~15 hues per canvas background (3px lines).
# path_order % N: adjacent slots are hue-separated; no yellow/green cluster.
_EDGE_COLORS_ON_DARK_BG: Tuple[str, ...] = (
    "#4FC3F7",
    "#E040FB",
    "#FF7043",
    "#26C6DA",
    "#FF5252",
    "#B388FF",
    "#FFA726",
    "#EC407A",
    "#5C6BC0",
    "#00ACC1",
    "#AB47BC",
    "#FF6E40",
    "#448AFF",
    "#F06292",
    "#7E57C2",
)
_EDGE_COLORS_ON_LIGHT_BG: Tuple[str, ...] = (
    "#1565C0",
    "#E65100",
    "#2E7D32",
    "#6A1B9A",
    "#C62828",
    "#F57F17",
    "#00838F",
    "#AD1457",
    "#283593",
    "#558B2F",
    "#4E342E",
    "#0277BD",
    "#D84315",
    "#4527A0",
    "#00695C",
)


def reference_graph_edge_color_theme(
    main_window=None, settings: Optional[dict] = None
) -> str:
    """'light' or 'dark' palette key (user/custom schemes use dark-background strokes)."""
    from theme.theme_service import resolved_ui_theme_from_settings

    if settings is None and main_window is not None:
        config = getattr(main_window, "config", None)
        if config is not None:
            settings = config.load_settings()
    resolved = resolved_ui_theme_from_settings(settings or {})
    return "light" if resolved == "light" else "dark"


def _edge_color_palette(theme: str) -> Tuple[str, ...]:
    if theme == "light":
        return _EDGE_COLORS_ON_LIGHT_BG
    return _EDGE_COLORS_ON_DARK_BG


def _assign_edge_colors(
    canonical: List[Tuple[str, str]],
    outgoing_lanes: Dict[str, List[Tuple[str, str]]],
    color_theme: str,
    path_order: Optional[Dict[str, int]] = None,
) -> Dict[Tuple[str, str], str]:
    """One palette color per source image (sequential by path_order); all outgoing edges match."""
    palette = _edge_color_palette(color_theme)
    n = len(palette)
    if n == 0:
        return {}

    color_map: Dict[Tuple[str, str], str] = {}
    if path_order is not None:
        for sp, edges in outgoing_lanes.items():
            idx = path_order.get(_norm_path(sp), path_order.get(sp, 0))
            color = palette[idx % n]
            for key in edges:
                if key in canonical:
                    color_map[key] = color
    else:
        for i, sp in enumerate(sorted(outgoing_lanes.keys())):
            color = palette[i % n]
            for key in outgoing_lanes[sp]:
                if key in canonical:
                    color_map[key] = color
    return color_map

# Channel separation between parallel routes (3px pen).
_GUTTER_LANE_SPACING = 20.0
_MIN_CHANNEL_SEP = 16.0
_COORD_BUCKET = 10
_DEConflict_TOL = 4.0
_MAX_DEConflict_PASSES = 4
# Attach x may differ slightly on the same visual column (in/out bands).
_COLUMN_ALIGN_X_TOL = 14.0


@dataclass
class GraphEdgeRoute:
    """Orthogonal polyline from source (tail) to target (arrowhead)."""

    source_path: str
    target_path: str
    points: List[QPointF] = field(default_factory=list)
    color: str = "#0088FF"


@dataclass
class ReferenceGraphLayoutResult:
    node_rects: Dict[str, QRect] = field(default_factory=dict)  # path -> cell rect
    edge_routes: List[GraphEdgeRoute] = field(default_factory=list)
    canvas_width: int = 800
    canvas_height: int = 600
    layers: Dict[str, int] = field(default_factory=dict)  # normpath -> layer index


def _assign_layers(
    graph: ReferenceGraph,
) -> Tuple[Dict[str, int], Dict[int, List[str]]]:
    """Assign nodes to layers via longest-path rank (sources at top, products below)."""
    norm_nodes = [_norm_path(p) for p in graph.nodes]
    node_set = set(norm_nodes)
    layers: Dict[str, int] = {n: 0 for n in norm_nodes}

    for _ in range(len(norm_nodes) + 1):
        changed = False
        for source, target in graph.edges:
            sn, tn = _norm_path(source), _norm_path(target)
            if sn not in node_set or tn not in node_set or sn == tn:
                continue
            new_layer = layers[sn] + 1
            if new_layer > layers[tn]:
                layers[tn] = new_layer
                changed = True
        if not changed:
            break

    by_layer: Dict[int, List[str]] = {}
    for n, layer in layers.items():
        by_layer.setdefault(layer, []).append(n)
    for layer_nodes in by_layer.values():
        layer_nodes.sort(key=lambda n: graph.path_order.get(n, 0))

    return layers, by_layer


def _assign_layers_from_focus(
    graph: ReferenceGraph,
) -> Tuple[Dict[str, int], Dict[int, List[str]]]:
    """Layer 0 = focus image (opened from); references in deeper rows below."""
    norm_nodes = [_norm_path(p) for p in graph.nodes]
    node_set = set(norm_nodes)
    focus = _norm_path(graph.focus_path) if graph.focus_path else ""
    if focus not in node_set and norm_nodes:
        focus = norm_nodes[0]

    layers: Dict[str, int] = {focus: 0}
    queue = [focus]
    head = 0
    while head < len(queue):
        n = queue[head]
        head += 1
        ln = layers[n]
        for source, target in graph.edges:
            tn, sn = _norm_path(target), _norm_path(source)
            if tn == n and sn in node_set and sn not in layers:
                layers[sn] = ln + 1
                queue.append(sn)

    max_l = max(layers.values()) if layers else 0
    for n in norm_nodes:
        if n not in layers:
            max_l += 1
            layers[n] = max_l

    by_layer: Dict[int, List[str]] = {}
    for n, layer in layers.items():
        by_layer.setdefault(layer, []).append(n)
    for layer_nodes in by_layer.values():
        layer_nodes.sort(key=lambda n: graph.path_order.get(n, 0))
    return layers, by_layer


def _barycenter_order(
    by_layer: Dict[int, List[str]],
    outgoing: Dict[str, Set[str]],
    incoming: Dict[str, Set[str]],
    path_order: Dict[str, int],
    iterations: int = 4,
) -> None:
    """Reduce crossings with barycenter heuristic (top-down + bottom-up)."""
    max_layer = max(by_layer.keys()) if by_layer else 0
    pos: Dict[str, float] = {}

    for _ in range(iterations):
        for layer in range(max_layer + 1):
            nodes = by_layer.get(layer, [])
            if not nodes:
                continue
            scored: List[Tuple[float, str]] = []
            for n in nodes:
                if layer == 0:
                    bary = float(path_order.get(n, 0))
                else:
                    parents = incoming.get(n, set())
                    parent_positions = [pos[p] for p in parents if p in pos]
                    bary = (
                        sum(parent_positions) / len(parent_positions)
                        if parent_positions
                        else float(path_order.get(n, 0))
                    )
                scored.append((bary, n))
            scored.sort(key=lambda t: (t[0], path_order.get(t[1], 0)))
            by_layer[layer] = [n for _, n in scored]
            for i, n in enumerate(by_layer[layer]):
                pos[n] = float(i)

        for layer in range(max_layer, -1, -1):
            nodes = by_layer.get(layer, [])
            if not nodes:
                continue
            scored = []
            for n in nodes:
                children = outgoing.get(n, set())
                child_positions = [pos[c] for c in children if c in pos]
                bary = (
                    sum(child_positions) / len(child_positions)
                    if child_positions
                    else float(path_order.get(n, 0))
                )
                scored.append((bary, n))
            scored.sort(key=lambda t: (t[0], path_order.get(t[1], 0)))
            by_layer[layer] = [n for _, n in scored]
            for i, n in enumerate(by_layer[layer]):
                pos[n] = float(i)


def _ideal_centers_for_layer(
    layer_nodes: List[str],
    incoming: Dict[str, Set[str]],
    outgoing: Dict[str, Set[str]],
    layer_centers: Dict[str, float],
    layer_of_node: Dict[str, int],
    path_order: Dict[str, int],
    content_left: float,
    content_width: float,
    layer_idx: int,
) -> Dict[str, float]:
    """Preferred center-x: under the image(s) this node feeds (focus-rooted layout)."""
    ideals: Dict[str, float] = {}
    n = len(layer_nodes)
    for i, node in enumerate(layer_nodes):
        if layer_idx == 0:
            ideals[node] = content_left + content_width / 2
            continue
        targets = [
            layer_centers[t]
            for t in outgoing.get(node, ())
            if t in layer_centers and layer_of_node.get(t, 999) < layer_idx
        ]
        if targets:
            ideals[node] = sum(targets) / len(targets)
        elif n == 1:
            ideals[node] = content_left + content_width / 2
        else:
            slot = path_order.get(node, i)
            ideals[node] = content_left + (slot + 0.5) * content_width / max(n, 1)
    return ideals


def _scatter_positions_in_layer(
    layer_nodes: List[str],
    ideal_centers: Dict[str, float],
    content_left: float,
    content_width: float,
    node_w: float,
) -> Dict[str, float]:
    """Place each node at the center of one of n equal columns (order from ideal centers)."""
    n = len(layer_nodes)
    if n == 0:
        return {}
    if n == 1:
        node = layer_nodes[0]
        return {node: content_left + content_width / 2 - node_w / 2}

    ordered = sorted(layer_nodes, key=lambda nd: ideal_centers.get(nd, 0))
    column_w = content_width / n
    out: Dict[str, float] = {}
    for i, nd in enumerate(ordered):
        center_x = content_left + (i + 0.5) * column_w
        out[nd] = center_x - node_w / 2
    return out


def _rect_blocks_segment(
    rect: QRect, x1: float, y1: float, x2: float, y2: float, pad: int = 4
) -> bool:
    """True if axis-aligned segment intersects *rect* (horizontal or vertical only)."""
    r = rect.adjusted(-pad, -pad, pad, pad)
    if abs(y1 - y2) < 0.5:
        y = y1
        xa, xb = (x1, x2) if x1 <= x2 else (x2, x1)
        if r.top() <= y <= r.bottom():
            return not (xb < r.left() or xa > r.right())
    if abs(x1 - x2) < 0.5:
        x = x1
        ya, yb = (y1, y2) if y1 <= y2 else (y2, y1)
        if r.left() <= x <= r.right():
            return not (yb < r.top() or ya > r.bottom())
    return False


def _gutter_x_clear_of_nodes(
    gutter_y: float,
    x1: float,
    x2: float,
    node_rects: Dict[str, QRect],
    layer_of_path: Dict[str, int],
    src_layer: int,
    tgt_layer: int,
) -> bool:
    """Horizontal segment at gutter_y from x1 to x2 must not cross node rows between layers."""
    xa, xb = (x1, x2) if x1 <= x2 else (x2, x1)
    for path, rect in node_rects.items():
        layer = layer_of_path.get(path, -1)
        if layer < src_layer or layer > tgt_layer:
            continue
        if _rect_blocks_segment(rect, xa, gutter_y, xb, gutter_y):
            return False
    return True


def _pick_gutter_lane_x(
    x_start: float,
    x_end: float,
    gutter_y: float,
    lane_index: int,
    lane_count: int,
    node_rects: Dict[str, QRect],
    layer_of_path: Dict[str, int],
    src_layer: int,
    tgt_layer: int,
    content_left: float,
    content_right: float,
) -> float:
    """Pick horizontal x in gutter that avoids crossing thumbnails."""
    base = (x_start + x_end) / 2.0
    spread = 18.0 * max(1, lane_count - 1)
    offsets = [0.0]
    for i in range(1, max(lane_count, 2)):
        offsets.extend([i * 18.0, -i * 18.0])
    order = sorted(range(len(offsets)), key=lambda i: abs(offsets[i]))
    for idx in order:
        if lane_count <= len(order) and idx != lane_index:
            continue
        x_lane = base + offsets[idx % len(offsets)]
        x_lane = max(content_left + 8, min(content_right - 8, x_lane))
        if _gutter_x_clear_of_nodes(
            gutter_y, x_start, x_lane, node_rects, layer_of_path, src_layer, tgt_layer
        ) and _gutter_x_clear_of_nodes(
            gutter_y, x_lane, x_end, node_rects, layer_of_path, src_layer, tgt_layer
        ):
            return x_lane
    return base


def _gutter_ys_between(
    src_rect: QRect,
    tgt_rect: QRect,
    gutter_centers: Dict[int, float],
    src_layer: int,
    tgt_layer: int,
) -> Tuple[List[float], bool]:
    """Gutter y values between two nodes; True if route goes downward on screen."""
    downward = src_rect.center().y() < tgt_rect.center().y()
    ys: List[float] = []
    if downward:
        lo, hi = src_layer, tgt_layer
        y_min, y_max = src_rect.bottom(), tgt_rect.top()
    else:
        lo, hi = tgt_layer, src_layer
        y_min, y_max = tgt_rect.bottom(), src_rect.top()
    for layer in range(lo, hi):
        gy = gutter_centers.get(layer)
        if gy is not None and y_min < gy < y_max:
            ys.append(gy)
    if not downward:
        ys.reverse()
    return ys, downward


def _channel_x_for_lane(
    lane_index: int,
    lane_count: int,
    content_left: float,
    content_width: float,
) -> float:
    """Dedicated vertical channel x so edges do not stack on the node column."""
    n = max(1, lane_count)
    frac = (lane_index + 1) / (n + 1)
    return content_left + frac * content_width


def _vertical_segment_clear(
    x: float,
    y_min: float,
    y_max: float,
    node_rects: Dict[str, QRect],
    pad: int = 6,
) -> bool:
    ya, yb = (y_min, y_max) if y_min <= y_max else (y_max, y_min)
    for rect in node_rects.values():
        r = rect.adjusted(-pad, -pad, pad, pad)
        if r.left() <= x <= r.right() and not (yb < r.top() or ya > r.bottom()):
            return False
    return True


def _pick_channel_x(
    lane_index: int,
    lane_count: int,
    content_left: float,
    content_width: float,
    gutter_ys: List[float],
    node_rects: Dict[str, QRect],
) -> float:
    """Staggered channel x that keeps the vertical spine out of thumbnails."""
    if not gutter_ys:
        return _channel_x_for_lane(lane_index, lane_count, content_left, content_width)
    y_min, y_max = min(gutter_ys), max(gutter_ys)
    base = _channel_x_for_lane(lane_index, lane_count, content_left, content_width)
    spread = max(24.0, content_width / max(8, lane_count + 2))
    candidates = [base]
    for i in range(1, max(lane_count, 3)):
        candidates.extend([base + i * spread, base - i * spread])
    margin = 12.0
    for cx in candidates:
        cx = max(content_left + margin, min(content_left + content_width - margin, cx))
        if _vertical_segment_clear(cx, y_min, y_max, node_rects):
            return cx
    return base


def _edge_sides(src_rect: QRect, tgt_rect: QRect) -> Tuple[str, str]:
    """Border sides to leave source and enter target (reference -> product)."""
    scy = src_rect.center().y()
    tcy = tgt_rect.center().y()
    if abs(scy - tcy) < 6:
        if src_rect.center().x() <= tgt_rect.center().x():
            return "right", "left"
        return "left", "right"
    if scy < tcy:
        return "bottom", "top"
    return "top", "bottom"


def _point_on_side(rect: QRect, side: str, frac: float) -> QPointF:
    """Point on the outer cell border; *frac* is 0..1 along that edge."""
    f = max(0.08, min(0.92, frac))
    if side == "top":
        return QPointF(float(rect.left()) + f * rect.width(), float(rect.top()))
    if side == "bottom":
        return QPointF(float(rect.left()) + f * rect.width(), float(rect.bottom()))
    if side == "left":
        return QPointF(float(rect.left()), float(rect.top()) + f * rect.height())
    return QPointF(float(rect.right()), float(rect.top()) + f * rect.height())


def _slot_frac(index: int, count: int) -> float:
    if count <= 1:
        return 0.5
    return (index + 1) / (count + 1)


# When both directions use the same border, incoming tips vs outgoing tails split the edge.
_INCOMING_BAND = (0.06, 0.42)
_OUTGOING_BAND = (0.58, 0.94)
_SOLO_BAND = (0.08, 0.92)


def _band_slot_frac(index: int, count: int, band_lo: float, band_hi: float) -> float:
    if count <= 1:
        return (band_lo + band_hi) / 2.0
    t = _slot_frac(index, count)
    return band_lo + t * (band_hi - band_lo)


def _attachment_frac_on_side(
    role: str, index: int, count: int, in_count: int, out_count: int
) -> float:
    """Fraction along a side for one attach point; in/out bands never overlap."""
    if in_count > 0 and out_count > 0:
        band = _INCOMING_BAND if role == "in" else _OUTGOING_BAND
    else:
        band = _SOLO_BAND
    return _band_slot_frac(index, count, band[0], band[1])


def _sort_neighbors(
    node_id: str,
    neighbor_ids: List[str],
    node_rects: Dict[str, QRect],
    side: str,
) -> List[str]:
    """Order neighbors along the edge so slots follow visual left-to-right or top-to-bottom."""
    uniq = sorted(set(neighbor_ids))

    def key(nid: str) -> float:
        c = node_rects[nid].center()
        if side in ("top", "bottom"):
            return c.x()
        return c.y()

    return sorted(uniq, key=key)


def _compute_edge_attachments(
    edge_list: List[Tuple[str, str]],
    node_rects: Dict[str, QRect],
) -> Dict[Tuple[str, str], Tuple[QPointF, QPointF]]:
    """Border attach points with exclusive in/out bands per (node, side)."""
    from collections import defaultdict

    edge_sides: Dict[Tuple[str, str], Tuple[str, str]] = {}
    for sp, tp in edge_list:
        sr = node_rects.get(sp)
        tr = node_rects.get(tp)
        if not sr or not tr:
            continue
        edge_sides[(sp, tp)] = _edge_sides(sr, tr)

    out_by_side: Dict[Tuple[str, str], List[str]] = defaultdict(list)
    in_by_side: Dict[Tuple[str, str], List[str]] = defaultdict(list)
    for sp, tp in edge_list:
        sides = edge_sides.get((sp, tp))
        if not sides:
            continue
        src_side, tgt_side = sides
        out_by_side[(sp, src_side)].append(tp)
        in_by_side[(tp, tgt_side)].append(sp)

    side_in_count: Dict[Tuple[str, str], int] = {
        key: len(set(sources)) for key, sources in in_by_side.items()
    }
    side_out_count: Dict[Tuple[str, str], int] = {
        key: len(set(targets)) for key, targets in out_by_side.items()
    }

    src_frac: Dict[Tuple[str, str], float] = {}
    tgt_frac: Dict[Tuple[str, str], float] = {}

    for (sp, side), targets in out_by_side.items():
        uniq = _sort_neighbors(sp, targets, node_rects, side)
        n_out = len(uniq)
        n_in = side_in_count.get((sp, side), 0)
        for i, tp in enumerate(uniq):
            src_frac[(sp, tp)] = _attachment_frac_on_side("out", i, n_out, n_in, n_out)

    for (tp, side), sources in in_by_side.items():
        uniq = _sort_neighbors(tp, sources, node_rects, side)
        n_in = len(uniq)
        n_out = side_out_count.get((tp, side), 0)
        for i, sp in enumerate(uniq):
            tgt_frac[(sp, tp)] = _attachment_frac_on_side("in", i, n_in, n_in, n_out)

    attachments: Dict[Tuple[str, str], Tuple[QPointF, QPointF]] = {}
    for sp, tp in edge_list:
        sr = node_rects.get(sp)
        tr = node_rects.get(tp)
        sides = edge_sides.get((sp, tp))
        if not sr or not tr or not sides:
            continue
        src_side, tgt_side = sides
        sf = src_frac.get((sp, tp), 0.5)
        tf = tgt_frac.get((sp, tp), 0.5)
        attachments[(sp, tp)] = (
            _point_on_side(sr, src_side, sf),
            _point_on_side(tr, tgt_side, tf),
        )
    return attachments


def _align_tail_to_head_on_border(
    attachments: Dict[Tuple[str, str], Tuple[QPointF, QPointF]],
    edge_list: List[Tuple[str, str]],
    node_rects: Dict[str, QRect],
) -> None:
    """Move the source attach onto the target's offset when it fits on the source border."""
    for sp, tp in edge_list:
        key = (sp, tp)
        pair = attachments.get(key)
        if not pair:
            continue
        sr = node_rects.get(sp)
        tr = node_rects.get(tp)
        if not sr or not tr:
            continue
        src_attach, tgt_attach = pair
        src_side, tgt_side = _edge_sides(sr, tr)

        if src_side in ("top", "bottom") and tgt_side in ("top", "bottom"):
            x = float(tgt_attach.x())
            if x < sr.left() or x > sr.right():
                ol = _rect_x_overlap(sr, tr)
                if ol is None:
                    continue
                x = max(ol[0], min(ol[1], x))
            else:
                ol = _rect_x_overlap(sr, tr)
                if ol is not None:
                    x = max(ol[0], min(ol[1], x))
            x = max(float(sr.left()), min(float(sr.right()), x))
            if abs(src_attach.x() - x) < 0.5:
                continue
            attachments[key] = (QPointF(x, src_attach.y()), tgt_attach)
            continue

        if src_side in ("left", "right") and tgt_side in ("left", "right"):
            y = float(tgt_attach.y())
            if y < sr.top() or y > sr.bottom():
                ol = _rect_y_overlap(sr, tr)
                if ol is None:
                    continue
                y = max(ol[0], min(ol[1], y))
            else:
                ol = _rect_y_overlap(sr, tr)
                if ol is not None:
                    y = max(ol[0], min(ol[1], y))
            y = max(float(sr.top()), min(float(sr.bottom()), y))
            if abs(src_attach.y() - y) < 0.5:
                continue
            attachments[key] = (QPointF(src_attach.x(), y), tgt_attach)


def _dedupe_polyline_points(pts: List[QPointF]) -> List[QPointF]:
    """Drop collinear duplicates but always keep polyline endpoints (attach + arrow)."""
    if len(pts) <= 2:
        return list(pts)
    out = [pts[0]]
    for p in pts[1:-1]:
        prev = out[-1]
        if abs(p.x() - prev.x()) > 0.5 or abs(p.y() - prev.y()) > 0.5:
            out.append(p)
    last = pts[-1]
    prev = out[-1]
    if abs(last.x() - prev.x()) > 0.5 or abs(last.y() - prev.y()) > 0.5:
        out.append(last)
    else:
        out.append(QPointF(last))
    return _trim_collinear_points(out)


def _trim_collinear_points(pts: List[QPointF]) -> List[QPointF]:
    """Remove middle points on the same horizontal or vertical segment."""
    if len(pts) <= 2:
        return pts
    out = [pts[0]]
    for i in range(1, len(pts) - 1):
        prev, cur, nxt = out[-1], pts[i], pts[i + 1]
        same_h = abs(prev.y() - cur.y()) < 0.5 and abs(cur.y() - nxt.y()) < 0.5
        same_v = abs(prev.x() - cur.x()) < 0.5 and abs(cur.x() - nxt.x()) < 0.5
        if same_h or same_v:
            continue
        out.append(cur)
    out.append(pts[-1])
    return out


def _layers_between(src_layer: int, tgt_layer: int) -> List[int]:
    if src_layer == tgt_layer:
        return []
    lo, hi = min(src_layer, tgt_layer), max(src_layer, tgt_layer)
    return list(range(lo, hi))


def _rect_x_overlap(a: QRect, b: QRect) -> Optional[Tuple[float, float]]:
    """Inclusive x span shared by both node rects, or None."""
    left = max(a.left(), b.left())
    right = min(a.right(), b.right())
    if left > right:
        return None
    return float(left), float(right)


def _rect_y_overlap(a: QRect, b: QRect) -> Optional[Tuple[float, float]]:
    top = max(a.top(), b.top())
    bottom = min(a.bottom(), b.bottom())
    if top > bottom:
        return None
    return float(top), float(bottom)


def _rects_share_column(src_rect: QRect, tgt_rect: QRect) -> bool:
    return _rect_x_overlap(src_rect, tgt_rect) is not None


def _rects_share_row(src_rect: QRect, tgt_rect: QRect) -> bool:
    return _rect_y_overlap(src_rect, tgt_rect) is not None


def _edge_uses_vertical_spine(
    src_attach: QPointF,
    tgt_attach: QPointF,
    src_rect: QRect,
    tgt_rect: QRect,
) -> bool:
    """Rects overlap in x — route a vertical spine (no offset channel)."""
    return (
        _rects_share_column(src_rect, tgt_rect)
        and abs(src_attach.y() - tgt_attach.y()) > 1.0
    )


def _edge_uses_horizontal_spine(
    src_attach: QPointF,
    tgt_attach: QPointF,
    src_rect: QRect,
    tgt_rect: QRect,
) -> bool:
    return (
        _rects_share_row(src_rect, tgt_rect)
        and abs(src_attach.x() - tgt_attach.x()) > 1.0
    )


def _best_column_x(
    src_attach: QPointF,
    tgt_attach: QPointF,
    ol_left: float,
    ol_right: float,
) -> float:
    """X in the shared column band; match target x so the arrow approach is vertical."""
    sx, tx = src_attach.x(), tgt_attach.x()
    in_s = ol_left <= sx <= ol_right
    in_t = ol_left <= tx <= ol_right
    if in_s and in_t:
        return tx
    if in_s:
        return sx
    if in_t:
        return tx
    return (ol_left + ol_right) / 2.0


def _shared_column_x(
    src_attach: QPointF,
    tgt_attach: QPointF,
    src_rect: QRect,
    tgt_rect: QRect,
) -> float:
    ol = _rect_x_overlap(src_rect, tgt_rect)
    if ol is None:
        return (src_rect.center().x() + tgt_rect.center().x()) / 2.0
    return _best_column_x(src_attach, tgt_attach, ol[0], ol[1])


def _best_row_y(
    src_attach: QPointF,
    tgt_attach: QPointF,
    top: float,
    bottom: float,
) -> float:
    sy, ty = src_attach.y(), tgt_attach.y()
    in_s = top <= sy <= bottom
    in_t = top <= ty <= bottom
    if in_s and in_t:
        return ty
    if in_s:
        return sy
    if in_t:
        return ty
    return (top + bottom) / 2.0


def _shared_row_y(
    src_attach: QPointF,
    tgt_attach: QPointF,
    src_rect: QRect,
    tgt_rect: QRect,
) -> float:
    ol = _rect_y_overlap(src_rect, tgt_rect)
    if ol is None:
        return (src_rect.center().y() + tgt_rect.center().y()) / 2.0
    return _best_row_y(src_attach, tgt_attach, ol[0], ol[1])


def _append_if_far(pts: List[QPointF], p: QPointF) -> None:
    if not pts:
        pts.append(p)
        return
    last = pts[-1]
    if abs(last.x() - p.x()) > 0.5 or abs(last.y() - p.y()) > 0.5:
        pts.append(p)


def _route_via_vertical_spine(
    src_attach: QPointF,
    tgt_attach: QPointF,
    src_rect: QRect,
    tgt_rect: QRect,
    gutter_y: Optional[float] = None,
) -> List[QPointF]:
    """Vertical spine; tail and head should already share x when column-aligned."""
    sx, tx = src_attach.x(), tgt_attach.x()
    x_r = sx if abs(sx - tx) < 0.5 else _shared_column_x(
        src_attach, tgt_attach, src_rect, tgt_rect
    )
    pts: List[QPointF] = [src_attach]
    if abs(sx - x_r) > 0.5:
        _append_if_far(pts, QPointF(x_r, src_attach.y()))
    if gutter_y is not None and abs(pts[-1].y() - gutter_y) > 0.5:
        _append_if_far(pts, QPointF(x_r, gutter_y))
    if abs(pts[-1].y() - tgt_attach.y()) > 0.5 or abs(pts[-1].x() - tgt_attach.x()) > 0.5:
        _append_if_far(pts, tgt_attach)
    return _dedupe_polyline_points(pts)


def _route_via_horizontal_spine(
    src_attach: QPointF,
    tgt_attach: QPointF,
    src_rect: QRect,
    tgt_rect: QRect,
    gutter_x: Optional[float] = None,
) -> List[QPointF]:
    """Horizontal spine; tail and head should already share y when row-aligned."""
    sy, ty = src_attach.y(), tgt_attach.y()
    y_r = sy if abs(sy - ty) < 0.5 else _shared_row_y(
        src_attach, tgt_attach, src_rect, tgt_rect
    )
    pts: List[QPointF] = [src_attach]
    if abs(sy - y_r) > 0.5:
        _append_if_far(pts, QPointF(src_attach.x(), y_r))
    if gutter_x is not None and abs(pts[-1].x() - gutter_x) > 0.5:
        _append_if_far(pts, QPointF(gutter_x, y_r))
    if abs(pts[-1].x() - tgt_attach.x()) > 0.5 or abs(pts[-1].y() - ty) > 0.5:
        _append_if_far(pts, tgt_attach)
    return _dedupe_polyline_points(pts)


def _polyline_is_single_column(pts: List[QPointF], tol: float = 1.0) -> bool:
    if len(pts) < 2:
        return False
    xs = [p.x() for p in pts]
    return max(xs) - min(xs) <= tol


def _enforce_orthogonal_polyline(pts: List[QPointF]) -> List[QPointF]:
    """Remove accidental diagonal segments (e.g. after deconflict nudges)."""
    if len(pts) < 2:
        return list(pts)
    out = [QPointF(pts[0])]
    for i in range(1, len(pts)):
        prev, cur = out[-1], QPointF(pts[i])
        if abs(cur.x() - prev.x()) > 0.5 and abs(cur.y() - prev.y()) > 0.5:
            _append_if_far(out, QPointF(cur.x(), prev.y()))
        _append_if_far(out, cur)
    return _dedupe_polyline_points(out)


def _assign_global_gutter_offsets(
    canonical: List[Tuple[str, str]],
    layer_of_path: Dict[str, int],
    gutter_centers: Dict[int, float],
    node_rects: Dict[str, QRect],
    attachments: Dict[Tuple[str, str], Tuple[QPointF, QPointF]],
) -> Dict[Tuple[str, str], Dict[int, float]]:
    """Per-edge Y offset per layer gap (global lane index within each gutter band)."""
    from collections import defaultdict

    gutter_edges: Dict[int, List[Tuple[str, str]]] = defaultdict(list)
    for sp, tp in canonical:
        sr, tr = node_rects.get(sp), node_rects.get(tp)
        pair = attachments.get((sp, tp))
        if not sr or not tr or not pair:
            continue
        if _edge_uses_vertical_spine(pair[0], pair[1], sr, tr):
            continue
        sl = layer_of_path.get(sp, 0)
        tl = layer_of_path.get(tp, 0)
        for layer in _layers_between(sl, tl):
            if layer in gutter_centers:
                gutter_edges[layer].append((sp, tp))

    offsets: Dict[Tuple[str, str], Dict[int, float]] = {}
    for layer, edges in gutter_edges.items():
        uniq = sorted(set(edges))
        n = len(uniq)
        for i, key in enumerate(uniq):
            off = (i - (n - 1) / 2.0) * _GUTTER_LANE_SPACING
            offsets.setdefault(key, {})[layer] = off
    return offsets


def _primary_gutter_offset(
    gutter_y_offsets: Dict[int, float], src_layer: int, tgt_layer: int
) -> float:
    layers = _layers_between(src_layer, tgt_layer)
    if not layers or not gutter_y_offsets:
        return 0.0
    mid = layers[len(layers) // 2]
    return gutter_y_offsets.get(mid, 0.0)


def _assign_global_vert_channels(
    canonical: List[Tuple[str, str]],
    attachments: Dict[Tuple[str, str], Tuple[QPointF, QPointF]],
    layer_of_path: Dict[str, int],
    node_rects: Dict[str, QRect],
    content_left: float,
    content_right: float,
) -> Dict[Tuple[str, str], float]:
    """Dedicated vertical spine X per edge so long column routes do not stack."""
    from collections import defaultdict

    groups: Dict[Tuple[int, int], List[Tuple[str, str]]] = defaultdict(list)
    for sp, tp in canonical:
        pair = attachments.get((sp, tp))
        if not pair:
            continue
        sl = layer_of_path.get(sp, 0)
        tl = layer_of_path.get(tp, 0)
        if sl == tl:
            continue
        if _edge_uses_vertical_spine(
            pair[0], pair[1], node_rects[sp], node_rects[tp]
        ) or _edge_uses_horizontal_spine(
            pair[0], pair[1], node_rects[sp], node_rects[tp]
        ):
            continue
        x_s = pair[0].x()
        bucket = int(round(x_s / _COORD_BUCKET))
        mid_layer = (_layers_between(sl, tl) or [sl])[len(_layers_between(sl, tl)) // 2]
        groups[(mid_layer, bucket)].append((sp, tp))

    channels: Dict[Tuple[str, str], float] = {}
    margin = 10.0
    for (_layer, _bucket), edges in groups.items():
        uniq = sorted(set(edges))
        n = len(uniq)
        for i, key in enumerate(uniq):
            x_s = attachments[key][0].x()
            off = (i - (n - 1) / 2.0) * _MIN_CHANNEL_SEP
            x_ch = max(content_left + margin, min(content_right - margin, x_s + off))
            channels[key] = x_ch
    return channels


def _orthogonal_polyline(
    src_attach: QPointF,
    tgt_attach: QPointF,
    src_rect: QRect,
    tgt_rect: QRect,
    src_layer: int,
    tgt_layer: int,
    gutter_centers: Dict[int, float],
    gutter_y_offset: float = 0.0,
    vert_channel_x: Optional[float] = None,
) -> List[QPointF]:
    """Orthogonal path with optional dedicated vertical channel X and gutter Y offset."""
    x_s, y_s = src_attach.x(), src_attach.y()
    x_t, y_t = tgt_attach.x(), tgt_attach.y()

    gutters, _downward = _gutter_ys_between(
        src_rect, tgt_rect, gutter_centers, src_layer, tgt_layer
    )
    g_y: Optional[float] = None
    if gutters:
        g_base = gutters[len(gutters) // 2]
        g_y = g_base + gutter_y_offset
        ya, yb = (y_s, y_t) if y_s <= y_t else (y_t, y_s)
        g_y = max(ya + 10.0, min(yb - 10.0, g_y))

    if _edge_uses_vertical_spine(src_attach, tgt_attach, src_rect, tgt_rect):
        return _enforce_orthogonal_polyline(
            _route_via_vertical_spine(
                src_attach, tgt_attach, src_rect, tgt_rect, gutter_y=g_y
            )
        )

    if _edge_uses_horizontal_spine(src_attach, tgt_attach, src_rect, tgt_rect):
        return _enforce_orthogonal_polyline(
            _route_via_horizontal_spine(src_attach, tgt_attach, src_rect, tgt_rect)
        )

    x_spine = vert_channel_x if vert_channel_x is not None else x_s

    if src_layer == tgt_layer:
        mid_y = (y_s + y_t) / 2.0 + gutter_y_offset
        if abs(x_s - x_t) > 0.5:
            if _rects_share_row(src_rect, tgt_rect):
                return _enforce_orthogonal_polyline(
                    _route_via_horizontal_spine(
                        src_attach, tgt_attach, src_rect, tgt_rect
                    )
                )
            return _enforce_orthogonal_polyline(
                _dedupe_polyline_points(
                    [src_attach, QPointF(x_s, mid_y), QPointF(x_t, mid_y), tgt_attach]
                )
            )
        return _enforce_orthogonal_polyline(
            _dedupe_polyline_points([src_attach, tgt_attach])
        )

    if not gutters:
        if _rects_share_column(src_rect, tgt_rect):
            return _enforce_orthogonal_polyline(
                _route_via_vertical_spine(
                    src_attach, tgt_attach, src_rect, tgt_rect, gutter_y=None
                )
            )
        mid_y = (y_s + y_t) / 2.0 + gutter_y_offset
        pts: List[QPointF] = [src_attach]
        if abs(x_spine - x_s) > 0.5:
            pts.append(QPointF(x_spine, y_s))
        pts.append(QPointF(x_spine, mid_y))
        if abs(x_t - x_spine) > 0.5:
            pts.append(QPointF(x_t, mid_y))
        pts.append(tgt_attach)
        return _enforce_orthogonal_polyline(_dedupe_polyline_points(pts))

    if _rects_share_column(src_rect, tgt_rect) and g_y is not None:
        return _enforce_orthogonal_polyline(
            _route_via_vertical_spine(
                src_attach, tgt_attach, src_rect, tgt_rect, gutter_y=g_y
            )
        )

    if _rects_share_column(src_rect, tgt_rect):
        return _enforce_orthogonal_polyline(
            _route_via_vertical_spine(
                src_attach, tgt_attach, src_rect, tgt_rect, gutter_y=g_y
            )
        )

    pts = [src_attach]
    if abs(x_spine - x_s) > 0.5:
        pts.append(QPointF(x_spine, y_s))
    if g_y is not None and abs(y_s - g_y) > 0.5:
        pts.append(QPointF(x_spine, g_y))
    if abs(x_t - x_spine) > 0.5:
        pts.append(QPointF(x_t, g_y))
    pts.append(tgt_attach)
    return _enforce_orthogonal_polyline(_dedupe_polyline_points(pts))


def _seg_axis_aligned(p1: QPointF, p2: QPointF) -> Optional[str]:
    if abs(p1.y() - p2.y()) < 0.5:
        return "h"
    if abs(p1.x() - p2.x()) < 0.5:
        return "v"
    return None


def _ranges_overlap(a0: float, a1: float, b0: float, b1: float, tol: float) -> bool:
    return a0 < b1 + tol and b0 < a1 + tol


def _nudge_points_on_coord(
    points: List[QPointF], coord: str, value: float, delta: float, tol: float = 1.0
) -> None:
    for i, p in enumerate(points):
        if coord == "y" and abs(p.y() - value) < tol:
            points[i] = QPointF(p.x(), p.y() + delta)
        elif coord == "x" and abs(p.x() - value) < tol:
            points[i] = QPointF(p.x() + delta, p.y())


def _deconflict_route_polylines(routes: List[GraphEdgeRoute]) -> None:
    """Several passes: separate overlapping horizontal (Y) and vertical (X) segments."""
    for _ in range(_MAX_DEConflict_PASSES):
        h_segs: List[Tuple[float, float, float, int, int]] = []
        v_segs: List[Tuple[float, float, float, int, int]] = []
        for ri, route in enumerate(routes):
            pts = route.points
            if _polyline_is_single_column(pts):
                continue
            for pi in range(len(pts) - 1):
                axis = _seg_axis_aligned(pts[pi], pts[pi + 1])
                if axis == "h":
                    y = (pts[pi].y() + pts[pi + 1].y()) / 2.0
                    h_segs.append(
                        (y, min(pts[pi].x(), pts[pi + 1].x()), max(pts[pi].x(), pts[pi + 1].x()), ri, pi)
                    )
                elif axis == "v":
                    x = (pts[pi].x() + pts[pi + 1].x()) / 2.0
                    v_segs.append(
                        (x, min(pts[pi].y(), pts[pi + 1].y()), max(pts[pi].y(), pts[pi + 1].y()), ri, pi)
                    )

        moved = False
        for i, h1 in enumerate(h_segs):
            for h2 in h_segs[i + 1 :]:
                if abs(h1[0] - h2[0]) >= _DEConflict_TOL:
                    continue
                if not _ranges_overlap(h1[1], h1[2], h2[1], h2[2], 2.0):
                    continue
                ri, pi, y = h2[3], h2[4], h2[0]
                if _polyline_is_single_column(routes[ri].points):
                    continue
                _nudge_points_on_coord(routes[ri].points, "y", y, _MIN_CHANNEL_SEP)
                moved = True

        for i, v1 in enumerate(v_segs):
            for v2 in v_segs[i + 1 :]:
                if abs(v1[0] - v2[0]) >= _DEConflict_TOL:
                    continue
                if not _ranges_overlap(v1[1], v1[2], v2[1], v2[2], 2.0):
                    continue
                ri, x = v2[3], v2[0]
                if _polyline_is_single_column(routes[ri].points):
                    continue
                _nudge_points_on_coord(routes[ri].points, "x", x, _MIN_CHANNEL_SEP)
                moved = True

        if moved:
            for route in routes:
                route.points = _enforce_orthogonal_polyline(
                    _dedupe_polyline_points(route.points)
                )
        else:
            break
    for route in routes:
        route.points = _enforce_orthogonal_polyline(
            _dedupe_polyline_points(route.points)
        )


def _route_edges(
    edge_list: List[Tuple[str, str]],
    node_rects: Dict[str, QRect],
    norm_to_path: Dict[str, str],
    layer_of_path: Dict[str, int],
    gutter_centers: Dict[int, float],
    color_theme: str = "dark",
    content_left: float = 0.0,
    content_width: float = 800.0,
    path_order: Optional[Dict[str, int]] = None,
) -> List[GraphEdgeRoute]:
    """Route each dependency; assign global X/Y channels, then deconflict overlaps."""
    from collections import defaultdict

    canonical: List[Tuple[str, str]] = []
    for source, target in edge_list:
        sn, tn = _norm_path(source), _norm_path(target)
        sp = norm_to_path.get(sn, source)
        tp = norm_to_path.get(tn, target)
        if sp in node_rects and tp in node_rects:
            canonical.append((sp, tp))

    attachments = _compute_edge_attachments(canonical, node_rects)
    _align_tail_to_head_on_border(attachments, canonical, node_rects)

    outgoing_lanes: Dict[str, List[Tuple[str, str]]] = defaultdict(list)
    for sp, tp in canonical:
        outgoing_lanes[sp].append((sp, tp))
    for sp in outgoing_lanes:
        outgoing_lanes[sp].sort(
            key=lambda st: (
                node_rects[st[1]].center().y(),
                node_rects[st[1]].center().x(),
            )
        )

    gutter_y_offsets = _assign_global_gutter_offsets(
        canonical, layer_of_path, gutter_centers, node_rects, attachments
    )
    content_right = content_left + content_width
    vert_channels = _assign_global_vert_channels(
        canonical,
        attachments,
        layer_of_path,
        node_rects,
        content_left,
        content_right,
    )

    color_map = _assign_edge_colors(
        canonical, outgoing_lanes, color_theme, path_order=path_order
    )
    default_color = _edge_color_palette(color_theme)[0]

    routes: List[GraphEdgeRoute] = []
    for sp, tp in canonical:
        src_rect = node_rects.get(sp)
        tgt_rect = node_rects.get(tp)
        pair = attachments.get((sp, tp))
        if not src_rect or not tgt_rect or not pair:
            continue
        src_attach, tgt_attach = pair
        sl = layer_of_path.get(sp, 0)
        tl = layer_of_path.get(tp, 0)
        key = (sp, tp)
        on_spine = _edge_uses_vertical_spine(
            src_attach, tgt_attach, src_rect, tgt_rect
        ) or _edge_uses_horizontal_spine(
            src_attach, tgt_attach, src_rect, tgt_rect
        )
        x_ch = vert_channels.get(key)
        x_s = src_attach.x()
        use_channel = (
            None
            if on_spine
            else (x_ch if x_ch is not None and abs(x_ch - x_s) > 0.5 else None)
        )
        g_off = (
            0.0
            if on_spine
            else _primary_gutter_offset(gutter_y_offsets.get(key, {}), sl, tl)
        )
        points = _orthogonal_polyline(
            src_attach,
            tgt_attach,
            src_rect,
            tgt_rect,
            sl,
            tl,
            gutter_centers,
            gutter_y_offset=g_off,
            vert_channel_x=use_channel,
        )
        routes.append(
            GraphEdgeRoute(
                source_path=sp,
                target_path=tp,
                points=points,
                color=color_map.get(key, default_color),
            )
        )

    _deconflict_route_polylines(routes)
    return routes


_LAYER_GAP = 64


def compute_reference_graph_dynamic_thumbnail_size(
    graph: ReferenceGraph,
    viewport_width: int,
    viewport_height: int,
    overlay_height: int = 0,
) -> int:
    """Largest square thumb size that fits the graph in the viewport (default / auto sizing)."""
    from thumbnails.thumbnail_constants import (
        BORDER_SPACE,
        CANVAS_TOTAL_BOTTOM_MARGIN,
        CANVAS_TOTAL_TOP_MARGIN,
        MAX_THUMBNAIL_SIZE,
        MIN_THUMBNAIL_SIZE,
        THUMBNAIL_SPACING,
    )

    if not graph.nodes:
        return MIN_THUMBNAIL_SIZE

    _, by_layer = _assign_layers_from_focus(graph)
    max_layer_count = max((len(nodes) for nodes in by_layer.values()), default=1)
    num_layers = len(by_layer)
    margin = BASE_MARGIN
    spacing = THUMBNAIL_SPACING
    overlay = max(0, overlay_height)

    available_width = max(200, viewport_width - 2 * margin)
    available_height = viewport_height - CANVAS_TOTAL_TOP_MARGIN - CANVAS_TOTAL_BOTTOM_MARGIN
    if available_width <= 0 or available_height <= 0:
        return MIN_THUMBNAIL_SIZE

    best = MIN_THUMBNAIL_SIZE
    for test_size in range(MIN_THUMBNAIL_SIZE, MAX_THUMBNAIL_SIZE + 1):
        node_w = test_size + BORDER_SPACE
        cell_outer = node_w + spacing
        cell_h = test_size + BORDER_SPACE + overlay
        row_width = max_layer_count * cell_outer - spacing
        if row_width > available_width:
            continue
        total_h = num_layers * (cell_h + spacing + _LAYER_GAP) - _LAYER_GAP
        if total_h > available_height:
            continue
        best = test_size
    return best


def compute_reference_graph_layout(
    graph: ReferenceGraph,
    viewport_width: int,
    thumbnail_size: int,
    overlay_height: int = 0,
    fit_to_viewport_width: bool = True,
    edge_color_theme: str = "dark",
) -> ReferenceGraphLayoutResult:
    """Compute node positions and edge routes for a reference dependency graph."""
    if not graph.nodes:
        return ReferenceGraphLayoutResult()

    norm_to_path: Dict[str, str] = {_norm_path(p): p for p in graph.nodes}
    layers, by_layer = _assign_layers_from_focus(graph)

    outgoing: Dict[str, Set[str]] = {n: set() for n in norm_to_path}
    incoming: Dict[str, Set[str]] = {n: set() for n in norm_to_path}
    edge_norm: List[Tuple[str, str]] = []
    for source, target in graph.edges:
        sn, tn = _norm_path(source), _norm_path(target)
        if sn in norm_to_path and tn in norm_to_path:
            outgoing[sn].add(tn)
            incoming[tn].add(sn)
            edge_norm.append((sn, tn))

    _barycenter_order(by_layer, outgoing, incoming, graph.path_order)

    margin = BASE_MARGIN
    spacing = THUMBNAIL_SPACING
    node_w = thumbnail_size + BORDER_SPACE
    cell_outer = node_w + spacing
    overlay = max(0, overlay_height)
    cell_h = thumbnail_size + BORDER_SPACE + overlay
    layer_gap = _LAYER_GAP
    content_width = max(200, viewport_width - 2 * margin)
    content_left = float(margin)

    max_layer_count = max((len(nodes) for nodes in by_layer.values()), default=1)
    needed_row_width = max_layer_count * cell_outer - spacing
    if (
        fit_to_viewport_width
        and needed_row_width > content_width
        and max_layer_count > 1
    ):
        node_w = max(thumbnail_size + BORDER_SPACE, (content_width - spacing) // max_layer_count)
        cell_outer = node_w + spacing
        needed_row_width = max_layer_count * cell_outer - spacing

    layout_content_width = (
        content_width
        if fit_to_viewport_width
        else max(content_width, needed_row_width)
    )

    node_rects: Dict[str, QRect] = {}
    gutter_centers: Dict[int, float] = {}
    layer_centers: Dict[str, float] = {}
    y = CANVAS_TOTAL_TOP_MARGIN
    max_layer = max(by_layer.keys()) if by_layer else 0

    for layer in range(max_layer + 1):
        layer_nodes = by_layer.get(layer, [])
        if not layer_nodes:
            continue
        layer_of_node = {norm_to_path[n]: l for n, l in layers.items() if n in norm_to_path}
        ideals = _ideal_centers_for_layer(
            layer_nodes,
            incoming,
            outgoing,
            layer_centers,
            layer_of_node,
            graph.path_order,
            content_left,
            layout_content_width,
            layer,
        )
        left_positions = _scatter_positions_in_layer(
            layer_nodes, ideals, content_left, layout_content_width, float(node_w)
        )
        row_top = y
        for n_norm in layer_nodes:
            path = norm_to_path[n_norm]
            left = left_positions[n_norm]
            node_rects[path] = QRect(int(left), int(row_top), int(node_w), int(cell_h))
            layer_centers[n_norm] = left + node_w / 2
        row_bottom = row_top + cell_h
        gutter_centers[layer] = row_bottom + layer_gap / 2.0
        y = row_bottom + spacing + layer_gap

    canvas_h = int(y - layer_gap + CANVAS_TOTAL_BOTTOM_MARGIN)
    canvas_w = max(viewport_width, margin * 2 + layout_content_width)
    layer_of_path = {
        norm_to_path[n]: l for n, l in layers.items() if n in norm_to_path
    }

    edge_routes = _route_edges(
        [(norm_to_path[s], norm_to_path[t]) for s, t in edge_norm],
        node_rects,
        norm_to_path,
        layer_of_path,
        gutter_centers,
        color_theme=edge_color_theme,
        content_left=content_left,
        content_width=layout_content_width,
        path_order=graph.path_order,
    )

    return ReferenceGraphLayoutResult(
        node_rects=node_rects,
        edge_routes=edge_routes,
        canvas_width=canvas_w,
        canvas_height=max(canvas_h, 200),
        layers={norm_to_path[n]: l for n, l in layers.items()},
    )
