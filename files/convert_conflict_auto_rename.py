#!/usr/bin/env python3
"""Rename planning for convert-conflict source files (similarity-based names)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Set, Tuple

from files.image_extensions_helpers import get_image_extensions
from files.photos_library_paths import is_inside_photos_library


@dataclass(frozen=True)
class ConvertConflictRenamePlanEntry:
    old_path: str
    new_path: str
    similar_path: str


def get_convert_conflict_target_paths(files: List[str], target_format: str) -> List[str]:
    """Existing output paths that block conversion (one per conflicting source)."""
    from files.convert_format import check_existing_files

    return list(check_existing_files(files, target_format))


def build_convert_conflict_context(
    source_files: List[str],
    target_format: str,
    group_path_pairs: List[Tuple[str, str]],
) -> Dict:
    """Session state for convert-conflict view and Auto Rename."""
    from files.convert_format import check_name_conflicts

    return {
        "target_format": target_format,
        "source_files": list(source_files),
        "group_path_pairs": list(group_path_pairs),
        "target_paths": get_convert_conflict_target_paths(source_files, target_format),
        "has_name_conflicts": bool(check_name_conflicts(source_files, target_format)),
    }


def _format_underscore_suffix(index: int) -> str:
    """Format _0001, _0002, ...; use more digits when index exceeds 9999."""
    width = max(4, len(str(index)))
    return f"_{index:0{width}d}"


def _reference_suffix_info(stem: str) -> Tuple[str, Optional[int], int]:
    """Split stem into (base, trailing_number, suffix_width) when stem ends with _NNNN (4+ digits)."""
    base, sep, suffix = stem.rpartition("_")
    if sep and suffix.isdigit() and len(suffix) >= 4:
        return base or stem, int(suffix), len(suffix)
    return stem, None, 0


def propose_unique_underscore_name(
    directory: str,
    stem: str,
    ext: str,
    reserved_names: Set[str],
) -> Optional[str]:
    """Return a path like stem_0001.ext not present on disk or in reserved_names."""
    if not ext.startswith("."):
        ext = f".{ext}"
    index = 1
    while index <= 10_000_000:
        new_name = f"{stem}{_format_underscore_suffix(index)}{ext}"
        new_path = os.path.join(directory, new_name)
        if new_path not in reserved_names and not os.path.exists(new_path):
            return new_path
        index += 1
    return None


def propose_unique_name_from_similar(
    directory: str,
    similar_path: str,
    ext: str,
    reserved_names: Set[str],
    planned_renames: Dict[str, str],
) -> Optional[str]:
    """
    Propose a unique path aligned with a similar reference file.

    When the reference stem ends with _NNNN (4+ digits), increment that number
    (e.g. Foo_1020_2030 -> Foo_1020_2031). Otherwise append _0001, _0002, ...
    """
    if not ext.startswith("."):
        ext = f".{ext}"

    if similar_path in planned_renames:
        reference_stem = os.path.splitext(os.path.basename(planned_renames[similar_path]))[0]
    else:
        reference_stem = os.path.splitext(os.path.basename(similar_path))[0]

    base, trailing, width = _reference_suffix_info(reference_stem)
    if trailing is not None:
        index = trailing + 1
        while index <= 10_000_000:
            suffix_width = max(4, width, len(str(index)))
            new_name = f"{base}_{index:0{suffix_width}d}{ext}"
            new_path = os.path.join(directory, new_name)
            if new_path not in reserved_names and not os.path.exists(new_path):
                return new_path
            index += 1
        return None

    return propose_unique_underscore_name(directory, base, ext, reserved_names)


def _list_same_dir_image_candidates(directory: str, exclude_paths: Set[str]) -> List[str]:
    extensions = get_image_extensions()
    candidates: List[str] = []
    try:
        with os.scandir(directory) as entries:
            for entry in entries:
                if not entry.is_file(follow_symlinks=False):
                    continue
                path = entry.path
                if path in exclude_paths:
                    continue
                ext = os.path.splitext(path)[1].lower()
                if ext not in extensions:
                    continue
                if is_inside_photos_library(path):
                    continue
                candidates.append(path)
    except OSError:
        return []
    return candidates


def _is_single_conflict_group(group_path_pairs: List[Tuple[str, str]]) -> bool:
    """True when exactly one conflict group with two paths."""
    if len(group_path_pairs) != 2:
        return False
    return len({group_key for group_key, _ in group_path_pairs}) == 1


def get_conflict_source_paths(context: Dict) -> List[str]:
    """Source files in conflict groups — targets for rename suggestions (not blocking outputs)."""
    source_files = set(context.get("source_files") or [])
    target_format = (context.get("target_format") or "").lower()
    target_ext = f".{target_format}" if target_format else ""

    seen: Set[str] = set()
    result: List[str] = []
    for _group_key, path in context.get("group_path_pairs") or []:
        if path not in source_files:
            continue
        if target_ext and os.path.splitext(path)[1].lower() == target_ext:
            continue
        if path in seen or not os.path.exists(path):
            continue
        seen.add(path)
        result.append(path)
    return result


def resolve_single_conflict_pair_order(
    group_path_pairs: List[Tuple[str, str]],
    source_files: List[str],
) -> List[Tuple[str, str]]:
    """Reorder a single conflict pair with the source file first."""
    if not _is_single_conflict_group(group_path_pairs):
        return list(group_path_pairs)

    group_key = group_path_pairs[0][0]
    paths = [path for _, path in group_path_pairs]
    source_set = set(source_files)
    ordered_paths = [p for p in paths if p in source_set]
    ordered_paths.extend(p for p in paths if p not in source_set)
    return [(group_key, path) for path in ordered_paths]


def _find_best_similar_match(
    sorter,
    target_path: str,
    directory: str,
    pending_rename_excludes: Set[str],
    planned_renames: Dict[str, str],
) -> Optional[str]:
    """Best CNN match among same-dir images, allowing planned renames as references."""
    external = _list_same_dir_image_candidates(directory, pending_rename_excludes)
    if not external:
        return None

    candidates = [target_path] + [p for p in external if p != target_path]
    try:
        ranked = sorter.reorder_by_similarity(candidates, target_path)
    except Exception:
        return None

    for path in ranked:
        if path not in pending_rename_excludes or path in planned_renames:
            return path
    return None


def build_convert_conflict_rename_plan(
    main_window,
    context: Dict,
    progress_callback: Optional[Callable[[int, int], None]] = None,
) -> Tuple[List[ConvertConflictRenamePlanEntry], List[str]]:
    """
    Build a dry-run rename plan for conflicted source files.

    Renames sources (e.g. PNG) to names aligned with their most similar directory images.
    Does not rename blocking output files or perform conversion.

    Returns (planned_renames, unresolved_paths).
    """
    conflict_sources = get_conflict_source_paths(context)
    if not conflict_sources:
        return [], []

    source_files: Set[str] = set(context.get("source_files") or [])
    blocking_outputs: Set[str] = set(context.get("target_paths") or [])

    main_window._ensure_cnn_sorter_initialized()
    sorter = main_window.cnn_image_similarity_sorter
    if sorter is None:
        return [], list(conflict_sources)

    rename_plan: List[ConvertConflictRenamePlanEntry] = []
    unresolved: List[str] = []
    reserved_names: Set[str] = source_files | blocking_outputs
    pending_rename_excludes: Set[str] = set(conflict_sources)
    planned_renames: Dict[str, str] = {}

    total = len(conflict_sources)
    for idx, source_path in enumerate(conflict_sources):
        if progress_callback:
            progress_callback(idx, total)

        if not os.path.exists(source_path):
            unresolved.append(source_path)
            pending_rename_excludes.discard(source_path)
            reserved_names.discard(source_path)
            continue

        directory = os.path.dirname(source_path)
        similar_path = _find_best_similar_match(
            sorter,
            source_path,
            directory,
            pending_rename_excludes,
            planned_renames,
        )
        if not similar_path:
            unresolved.append(source_path)
            continue

        new_path = propose_unique_name_from_similar(
            directory,
            similar_path,
            os.path.splitext(source_path)[1],
            reserved_names,
            planned_renames,
        )
        if not new_path:
            unresolved.append(source_path)
            continue

        rename_plan.append(
            ConvertConflictRenamePlanEntry(
                old_path=source_path,
                new_path=new_path,
                similar_path=similar_path,
            )
        )
        planned_renames[source_path] = new_path
        reserved_names.add(new_path)
        pending_rename_excludes.discard(source_path)

    if progress_callback:
        progress_callback(total, total)

    return rename_plan, unresolved


# Set True when UI should allow applying the rename plan from the plan dialog.
CONVERT_CONFLICT_RENAME_APPLY_ENABLED = True


def _execute_rename_plan_phases(
    rename_plan: Dict,
    progress_callback: Optional[Callable[[int, int, str], None]] = None,
) -> Tuple[List[Tuple[str, str]], List[str]]:
    """Run phase0/1/2 os.rename steps. Returns (completed as (current, original), errors)."""
    phase0 = rename_plan.get("phase0") or []
    phase1 = rename_plan.get("phase1") or []
    phase2 = rename_plan.get("phase2") or []
    total_ops = len(phase0) + len(phase1) + len(phase2)
    completed: List[Tuple[str, str]] = []
    errors: List[str] = []
    op_idx = 0

    def _step(source_path: str, target_path: str, label: str) -> None:
        nonlocal op_idx
        if progress_callback:
            progress_callback(op_idx, total_ops, label)
        op_idx += 1
        if source_path == target_path:
            return
        try:
            os.rename(source_path, target_path)
            completed.append((target_path, source_path))
        except OSError as exc:
            errors.append(
                f"Failed to rename {os.path.basename(source_path)}: {exc}"
            )

    for source_path, target_path in phase0:
        _step(source_path, target_path, f"Moving {os.path.basename(source_path)}...")
    for source_path, target_path in phase1:
        _step(source_path, target_path, f"Renaming {os.path.basename(source_path)}...")
    for temp_path, final_path in phase2:
        _step(temp_path, final_path, f"Finalizing {os.path.basename(final_path)}...")

    return completed, errors


def _remap_paths_in_convert_conflict_view(main_window, path_map: Dict[str, str]) -> None:
    """Update displayed paths after conflict source renames."""
    if not path_map:
        return

    if getattr(main_window, "displayed_images", None):
        main_window.displayed_images = [
            path_map.get(p, p) for p in main_window.displayed_images
        ]

    ctx = getattr(main_window, "convert_conflict_context", None)
    if ctx:
        ctx["source_files"] = [
            path_map.get(p, p) for p in (ctx.get("source_files") or [])
        ]
        ctx["target_paths"] = [
            path_map.get(p, p) for p in (ctx.get("target_paths") or [])
        ]
        new_pairs = []
        for group_key, path in ctx.get("group_path_pairs") or []:
            new_pairs.append((group_key, path_map.get(path, path)))
        ctx["group_path_pairs"] = new_pairs

    if getattr(main_window, "selected_files", None):
        main_window.selected_files = {
            path_map.get(p, p) for p in main_window.selected_files
        }

    current = None
    if hasattr(main_window, "get_current_image_path"):
        current = main_window.get_current_image_path()
    elif hasattr(main_window, "current_image_path"):
        current = main_window.current_image_path

    if current and current in path_map:
        new_current = path_map[current]
        if hasattr(main_window, "set_current_image_by_path"):
            main_window.set_current_image_by_path(new_current, fallback_index=0)
        else:
            main_window.current_image_path = new_current

    if hasattr(main_window, "thumbnail_container") and main_window.thumbnail_container:
        canvas = main_window.thumbnail_container.canvas
        if hasattr(canvas, "reorder_thumbnails"):
            canvas.reorder_thumbnails(
                main_window.displayed_images, force_recalculate_grid=True
            )

    if hasattr(main_window, "highlight_image"):
        main_window.highlight_image()
    if hasattr(main_window, "_emit_selection_changed"):
        main_window._emit_selection_changed(getattr(main_window, "highlight_index", None))
    if hasattr(main_window, "update_status_bar_sections"):
        main_window.update_status_bar_sections()


def refresh_convert_conflict_view_after_renames(main_window) -> None:
    """Rebuild convert-conflict thumbnail view from disk after conflict sources are renamed."""
    ctx = getattr(main_window, "convert_conflict_context", None)
    if not ctx:
        return

    from sort_mode import SortMode

    if getattr(main_window, "current_sort_mode", None) != SortMode.DUPLICATES:
        return

    source_files = list(ctx.get("source_files") or [])
    target_format = ctx.get("target_format") or ""
    if not source_files or not target_format:
        return

    from files.convert_format import get_existing_conflict_group_pairs
    from files.file_operations_manager import _present_duplicate_groups_browse_view

    group_path_pairs = get_existing_conflict_group_pairs(source_files, target_format)
    if not group_path_pairs:
        main_window.convert_conflict_context = None
        if hasattr(main_window, "update_convert_conflict_auto_rename_button"):
            main_window.update_convert_conflict_auto_rename_button()
        return

    group_path_pairs = resolve_single_conflict_pair_order(
        group_path_pairs,
        source_files,
    )

    convert_context = build_convert_conflict_context(
        source_files, target_format, group_path_pairs
    )
    conflict_paths = {path for _, path in group_path_pairs}
    current_image_path = None
    if hasattr(main_window, "get_current_image_path"):
        candidate = main_window.get_current_image_path()
        if candidate in conflict_paths:
            current_image_path = candidate

    _present_duplicate_groups_browse_view(
        main_window,
        group_path_pairs,
        current_image_path,
        f"Convert conflicts ({len(group_path_pairs)} files)",
        auto_select=False,
        convert_conflict_context=convert_context,
    )


def sync_convert_session_source_files(main_window, path_map: Dict[str, str]) -> None:
    """Update convert session file lists after a source path was renamed."""
    if not path_map:
        return

    pending_files = getattr(main_window, "convert_format_pending_files", None)
    if pending_files is not None:
        main_window.convert_format_pending_files = [
            path_map.get(p, p) for p in pending_files
        ]


def apply_convert_conflict_renames(
    main_window,
    entries: List[ConvertConflictRenamePlanEntry],
) -> Tuple[int, List[str]]:
    """
    Apply selected conflict-source renames.

    Returns (success_count, error_messages). Rolls back completed renames on failure.
    """
    if not entries:
        return 0, []

    fom = getattr(main_window, "file_operations_manager", None)
    if fom is None:
        return 0, ["File operations manager is not available."]

    from collections import defaultdict

    from PySide6.QtWidgets import QApplication

    from utils import create_file_operation_progress_dialog, show_styled_critical

    by_directory: Dict[str, List[ConvertConflictRenamePlanEntry]] = defaultdict(list)
    for entry in entries:
        if not os.path.exists(entry.old_path):
            continue
        if os.path.exists(entry.new_path):
            return 0, [f"Target already exists: {os.path.basename(entry.new_path)}"]
        by_directory[os.path.dirname(entry.old_path)].append(entry)

    path_map: Dict[str, str] = {}
    all_errors: List[str] = []
    success_count = 0

    total_entries = sum(len(v) for v in by_directory.values())
    progress = create_file_operation_progress_dialog(
        main_window, "Renaming Files", max(total_entries, 1)
    )
    progress_idx = 0

    try:
        for directory, dir_entries in sorted(by_directory.items()):
            target_mappings = [(e.old_path, e.new_path) for e in dir_entries]
            temp_prefix = fom._find_available_temp_prefix(directory)
            rename_plan = fom._build_efficient_rename_plan(
                target_mappings, directory, temp_prefix
            )
            if not rename_plan:
                all_errors.append(f"Could not build rename plan for {directory}")
                continue

            def phase_progress(done, total, _label):
                pass

            completed, errors = _execute_rename_plan_phases(rename_plan, phase_progress)
            if errors:
                for current_path, original_path in reversed(completed):
                    try:
                        if os.path.exists(current_path) and current_path != original_path:
                            os.rename(current_path, original_path)
                    except OSError:
                        pass
                all_errors.extend(errors)
                show_styled_critical(
                    main_window,
                    "Rename Failed",
                    "Some rename operations failed:\n\n"
                    + "\n".join(f"  • {e}" for e in errors[:10]),
                )
                return success_count, all_errors

            for entry in dir_entries:
                path_map[entry.old_path] = entry.new_path
                success_count += 1
                progress_idx += 1
                progress.setValue(progress_idx)
                progress.setLabelText(
                    f"Renamed {os.path.basename(entry.old_path)}"
                )
                QApplication.processEvents()
    finally:
        progress.close()

    if path_map:
        if hasattr(main_window, "cache_manager") and main_window.cache_manager:
            try:
                main_window.cache_manager.clear_cache_for_files_batch(list(path_map.keys()))
            except Exception:
                pass
        _remap_paths_in_convert_conflict_view(main_window, path_map)
        sync_convert_session_source_files(main_window, path_map)
        refresh_convert_conflict_view_after_renames(main_window)

    return success_count, all_errors

