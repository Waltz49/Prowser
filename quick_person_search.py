#!/usr/bin/env python3
"""
Quick Person Search: for 1–4 selected images, save face samples under the known-faces
subject "Z Quick Person", then open Search by person (cmd-P). When multiple faces are in
one image, a dialog shows the image with boxes; the clicked face is used. Single-face
images use that face directly. The person dialog shows one 96px thumbnail (first sample).
"""

import os
from typing import Any

# Reserved subject name for quick multi-sample search (max 4 samples).
QUICK_PERSON_SUBJECT_NAME = "Z Quick Person"

MAX_QUICK_PERSON_IMAGES = 4

# Match previous quick-person encoding quality (was get_largest_face_encoding_from_path).
_QUICK_PERSON_ENCODING_MODEL = "large"


def get_deduped_selected_image_paths(main_window) -> list[str]:
    """Existing file paths from current selection, display order, unique by normpath."""
    mw = main_window
    if not hasattr(mw, "selection_manager") or not mw.selection_manager:
        return []
    sel = mw.selection_manager.get_selected_files()
    out: list[str] = []
    seen: set[str] = set()
    for p in sel:
        if not p or not os.path.isfile(p):
            continue
        nk = os.path.normpath(p)
        if nk in seen:
            continue
        seen.add(nk)
        out.append(p)
    return out


def _subject_id_for_quick_person() -> str | None:
    """Return subject id for QUICK_PERSON_SUBJECT_NAME, creating the subject if needed."""
    from known_faces_manager import list_subjects, add_subject

    for s in list_subjects():
        if (s.get("name") or "").strip() == QUICK_PERSON_SUBJECT_NAME:
            return s.get("id")
    return add_subject(QUICK_PERSON_SUBJECT_NAME)


def _replace_all_samples(subject_id: str, path_embeddings: list[tuple[str, list]]) -> bool:
    """Clear subject samples, then add each (path, embedding) in order (len <= 4)."""
    from known_faces_manager import get_subject, remove_sample, add_sample

    if not get_subject(subject_id):
        return False
    while True:
        sub = get_subject(subject_id)
        samples = sub.get("samples") or []
        if not samples:
            break
        if not remove_sample(subject_id, 0):
            return False
    for image_path, embedding in path_embeddings:
        if not add_sample(subject_id, image_path, embedding):
            return False
    return True


def run_quick_person_search(main_window) -> None:
    """Entry point from Search > Quick Person Search."""
    from PySide6.QtWidgets import QDialog
    from utils import show_styled_warning
    from face_engine import is_available, get_faces_with_locations_and_rgb_from_path
    from quick_person_face_pick_dialog import QuickPersonFacePickDialog

    mw = main_window
    if getattr(mw, "current_view_mode", None) not in ("thumbnail", "browse"):
        return

    if not is_available():
        show_styled_warning(mw, "Quick Person Search", "Face recognition is not available.")
        return

    paths = get_deduped_selected_image_paths(mw)
    if len(paths) > MAX_QUICK_PERSON_IMAGES:
        show_styled_warning(
            mw,
            "Quick Person Search",
            f"Too many images selected ({len(paths)}).\nSelect at most {MAX_QUICK_PERSON_IMAGES} images.",
        )
        return
    if not paths:
        show_styled_warning(
            mw,
            "Quick Person Search",
            "No images selected.\nSelect 1 to 4 images with at least one face each.",
        )
        return

    path_rows: list[tuple[str, list, Any, tuple[int, int, int, int]]] = []
    errors: list[str] = []
    for path in paths:
        preview_pm = None
        detections, rgb = get_faces_with_locations_and_rgb_from_path(
            path, encoding_model=_QUICK_PERSON_ENCODING_MODEL
        )
        if not detections:
            errors.append(f"{path}\n  No faces found or could not encode.")
            continue

        if len(detections) > 1:
            # Left-to-right, then top-to-bottom (face_recognition order is not spatial).
            detections = sorted(list(detections), key=lambda d: (d[0][3], d[0][0]))

        emb: list | None = None
        chosen_index: int = 0
        if len(detections) == 1:
            emb = list(detections[0][1])
            chosen_index = 0
        else:
            if rgb is None:
                errors.append(f"{path}\n  No faces found or could not encode.")
                continue
            from PIL import Image
            from exif_image_loader import pil_to_qpixmap

            preview = pil_to_qpixmap(Image.fromarray(rgb), preserve_alpha=False)
            if preview is None or preview.isNull():
                errors.append(f"{path}\n  Could not build preview for face picker.")
                continue
            preview_pm = preview
            dlg = QuickPersonFacePickDialog(mw, detections, preview)
            if dlg.exec() != QDialog.DialogCode.Accepted:
                return
            res = dlg.get_result()
            if not res:
                return
            chosen_index, emb = res

        if not emb or len(emb) != 128:
            errors.append(f"{path}\n  No faces found or could not encode.")
            continue

        if getattr(mw, "debug_mode", False):
            import numpy as np

            ref = np.array(detections[chosen_index][1], dtype=np.float64)
            got = np.array(emb, dtype=np.float64)
            if ref.shape != got.shape or not np.allclose(ref, got):
                print(
                    f"[Quick Person] debug: embedding mismatch for face index {chosen_index} path={path!r}"
                )
            else:
                print(
                    f"[Quick Person] debug: face index {chosen_index} embedding matches detection path={path!r}"
                )
            if preview_pm is not None and rgb is not None:
                if preview_pm.width() != rgb.shape[1] or preview_pm.height() != rgb.shape[0]:
                    print(
                        f"[Quick Person] debug: preview size {preview_pm.width()}x{preview_pm.height()} "
                        f"!= rgb {rgb.shape[1]}x{rgb.shape[0]} path={path!r}"
                    )

        trbl = detections[chosen_index][0]
        picked_trbl = (int(trbl[0]), int(trbl[1]), int(trbl[2]), int(trbl[3]))
        path_rows.append((path, emb, rgb, picked_trbl))

    if errors:
        warning_title = "Quick Person Search"
        if len(paths) == 1:
            warning_body = f"No faces were found.\n\n{'\n\n'.join(errors)}"
        else:
            warning_body = f"Some images could not be used.\n\n{'\n\n'.join(errors)}"
        show_styled_warning(mw, warning_title, warning_body)
        return


    if not path_rows:
        show_styled_warning(mw, "Quick Person Search", "No valid face samples to save.")
        return

    sid = _subject_id_for_quick_person()
    if not sid:
        show_styled_warning(
            mw,
            "Quick Person Search",
            f'Could not create or find the "{QUICK_PERSON_SUBJECT_NAME}" person.',
        )
        return

    path_embeddings = [(p, e) for p, e, _rgb, _tr in path_rows]
    if not _replace_all_samples(sid, path_embeddings):
        show_styled_warning(mw, "Quick Person Search", "Could not save the face samples.")
        return

    try:
        from face_sample_thumbnail import ensure_face_sample_thumbnail
        for path, emb, rgb, picked_trbl in path_rows:
            try:
                ensure_face_sample_thumbnail(
                    path, emb, alignment_rgb=rgb, picked_face_trbl=picked_trbl
                )
            except Exception:
                pass
    except Exception:
        pass
    try:
        mw.on_known_faces_external_update()
    except Exception:
        pass

    try:
        mw.config.update_setting("find_person_subject_id", sid)
    except Exception:
        pass

    tree_had_focus = mw._tree_has_focus() if hasattr(mw, "_tree_has_focus") else False
    mw._tree_had_focus_when_invoked = tree_had_focus
    try:
        mw.show_filter_by_person_dialog()
    finally:
        mw._tree_had_focus_when_invoked = False
