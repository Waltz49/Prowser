#!/usr/bin/env python3
"""EXIF reference parsing and dependency graph construction for reference levels."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

_LEGACY_REF_MD5_LINE = re.compile(r"^[0-9a-fA-F]{32}$")
_REF_FILEDATE_LINE = re.compile(r"^\d+(?:\.\d+)?$")
_REF_SECTION_STOP = re.compile(
    r"^(?:prompt|image model|title|description):$", re.IGNORECASE
)
_REF_FILEDATE_TOLERANCE_S = 1.0


def _norm_path(path: str) -> str:
    return os.path.normpath(os.path.abspath(path))


def parse_reference_entries_from_lines(
    lines: List[str], start: int
) -> List[Tuple[str, Optional[float]]]:
    """Parse (label, optional_mtime) from References body lines; skip legacy MD5 lines."""
    entries: List[Tuple[str, Optional[float]]] = []
    i = start
    while i < len(lines):
        label = lines[i].strip()
        if not label:
            i += 1
            continue
        if _REF_SECTION_STOP.match(label):
            break
        if _LEGACY_REF_MD5_LINE.fullmatch(label):
            i += 1
            continue
        expected_mtime: Optional[float] = None
        if i + 1 < len(lines):
            nxt = lines[i + 1].strip()
            if _LEGACY_REF_MD5_LINE.fullmatch(nxt):
                entries.append((label, None))
                i += 2
                continue
            if _REF_FILEDATE_LINE.fullmatch(nxt):
                try:
                    expected_mtime = float(nxt)
                except ValueError:
                    expected_mtime = None
                entries.append((label, expected_mtime))
                i += 2
                continue
        entries.append((label, None))
        i += 1
    return entries


def parse_reference_entries_from_text(text: str) -> List[Tuple[str, Optional[float]]]:
    """Parse References block in EXIF user comment."""
    if not text:
        return []
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if line.strip().lower() == "references:":
            return parse_reference_entries_from_lines(lines, i + 1)
    return []


def resolve_reference_path(
    image_dir: str, fname: str, expected_mtime: Optional[float] = None
) -> Optional[str]:
    candidates: List[str] = []
    if fname.startswith("~") or os.path.isabs(fname) or "/" in fname:
        try:
            candidates.append(os.path.normpath(os.path.abspath(os.path.expanduser(fname))))
        except (OSError, ValueError):
            pass
    rel = fname[2:] if fname.startswith("./") else fname
    candidates.append(os.path.normpath(os.path.join(image_dir, rel)))
    for cand in candidates:
        if not os.path.isfile(cand):
            continue
        if expected_mtime is not None:
            try:
                if abs(os.path.getmtime(cand) - expected_mtime) > _REF_FILEDATE_TOLERANCE_S:
                    continue
            except OSError:
                continue
        return cand
    return None


def resolve_reference_entries_map(
    image_dir: str,
    current_path: str,
    entries: List[Tuple[str, Optional[float]]],
) -> Dict[str, str]:
    """Map reference label (lower) -> resolved file path (filedate match when stored)."""
    resolved: Dict[str, str] = {}
    if not current_path or not os.path.isfile(current_path):
        return resolved
    for fname, expected_mtime in entries:
        key = fname.strip().lower()
        if key in resolved:
            continue
        path = resolve_reference_path(image_dir, fname, expected_mtime)
        if path:
            resolved[key] = path
    return resolved


def get_reference_entries_for_path(image_path: str) -> List[Tuple[str, Optional[float]]]:
    """Read reference entries from EXIF description on *image_path*."""
    if not image_path or not os.path.isfile(image_path):
        return []
    try:
        from exif_utils import (
            get_exif_dict_named_from_image_path,
            get_user_description_from_exif_dict,
        )

        exif_dict = get_exif_dict_named_from_image_path(image_path)
        desc = get_user_description_from_exif_dict(exif_dict)
        if not desc:
            return []
        return parse_reference_entries_from_text(str(desc))
    except Exception:
        return []


def collect_reference_chain_paths(
    image_dir: str, root_path: str, entries: List[Tuple[str, Optional[float]]]
) -> List[str]:
    """Preorder traversal of EXIF References; skip paths and labels already seen."""
    if not root_path or not os.path.isfile(root_path):
        return []
    seen_paths: Set[str] = set()
    seen_names: Set[str] = set()
    out: List[str] = []

    def visit(path: str, direct_entries: List[Tuple[str, Optional[float]]]) -> None:
        pn = os.path.normpath(path)
        if pn in seen_paths:
            return
        seen_paths.add(pn)
        out.append(path)
        local_dir = os.path.dirname(path) or image_dir
        resolved = resolve_reference_entries_map(local_dir, path, direct_entries)
        for fname, _expected_mtime in direct_entries:
            name_key = fname.strip().lower()
            if name_key in seen_names:
                continue
            ref_path = resolved.get(name_key)
            if not ref_path:
                continue
            rpn = os.path.normpath(ref_path)
            if rpn in seen_paths:
                seen_names.add(name_key)
                continue
            seen_names.add(name_key)
            child_entries = get_reference_entries_for_path(ref_path)
            visit(ref_path, child_entries)

    visit(root_path, entries)
    return out


def resolve_exif_reference_paths(
    image_dir: str, current_path: str, entries: List[Tuple[str, Optional[float]]]
) -> Tuple[List[str], Dict[str, str]]:
    """Resolve direct reference filenames (basename, or ~ / absolute path)."""
    empty_map: Dict[str, str] = {}
    if not current_path or not os.path.isfile(current_path):
        return [], empty_map
    resolved = resolve_reference_entries_map(image_dir, current_path, entries)
    out: List[str] = []
    seen_paths: Set[str] = set()
    out.append(current_path)
    seen_paths.add(os.path.normpath(current_path))
    for fn, _expected_mtime in entries:
        p = resolved.get(fn.strip().lower())
        if not p:
            continue
        pn = os.path.normpath(p)
        if pn not in seen_paths:
            out.append(p)
            seen_paths.add(pn)
    return out, resolved


@dataclass
class ReferenceGraph:
    """Dependency graph for a reference level (paths + directed edges)."""

    nodes: List[str]
    edges: List[Tuple[str, str]]  # (source, target) reference -> product
    path_order: Dict[str, int] = field(default_factory=dict)  # normpath -> preorder index
    focus_path: Optional[str] = None  # image from which reflevel was opened (top row)

    def __post_init__(self) -> None:
        if not self.path_order:
            self.path_order = {_norm_path(p): i for i, p in enumerate(self.nodes)}


def build_reference_graph(
    paths: List[str], focus_path: Optional[str] = None
) -> ReferenceGraph:
    """Build edges from EXIF References for paths in *paths* (both endpoints must be in set)."""
    if not paths:
        return ReferenceGraph(nodes=[], edges=[])

    canonical: List[str] = []
    norm_to_path: Dict[str, str] = {}
    for p in paths:
        if not p or not os.path.isfile(p):
            continue
        np = _norm_path(p)
        if np not in norm_to_path:
            norm_to_path[np] = p
            canonical.append(p)

    path_set = set(norm_to_path.keys())
    path_order = {np: i for i, p in enumerate(canonical) for np in [_norm_path(p)]}
    edges: List[Tuple[str, str]] = []
    seen_edges: Set[Tuple[str, str]] = set()

    for target_path in canonical:
        target_norm = _norm_path(target_path)
        image_dir = os.path.dirname(target_path) or ""
        entries = get_reference_entries_for_path(target_path)
        resolved = resolve_reference_entries_map(image_dir, target_path, entries)
        for fname, _mtime in entries:
            source_path = resolved.get(fname.strip().lower())
            if not source_path:
                continue
            source_norm = _norm_path(source_path)
            if source_norm not in path_set or source_norm == target_norm:
                continue
            source_canon = norm_to_path[source_norm]
            target_canon = norm_to_path[target_norm]
            edge = (source_canon, target_canon)
            edge_key = (_norm_path(source_canon), _norm_path(target_canon))
            if edge_key in seen_edges:
                continue
            seen_edges.add(edge_key)
            edges.append(edge)

    focus = None
    if focus_path and os.path.isfile(focus_path):
        fn = _norm_path(focus_path)
        if fn in path_set:
            focus = norm_to_path[fn]
    if focus is None and canonical:
        focus = canonical[0]
    return ReferenceGraph(
        nodes=canonical, edges=edges, path_order=path_order, focus_path=focus
    )
