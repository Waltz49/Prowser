#!/usr/bin/env python3
"""
Shared 96x96 face sample thumbnails for Settings > Faces and Search by person dialog.
Uses face_sample_cache (disk + by_face_key) with the same crop rules as the Faces tab.
"""

from __future__ import annotations

import os
from typing import Any, List, Optional, Tuple

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap

# dlib / face_recognition: right and bottom are exclusive pixel indices.
_TRBL = Tuple[int, int, int, int]


def _build_face_crop_pixmap(
    image_path: str,
    sample_embedding: List[float],
    *,
    encoding_model: Optional[str] = None,
    alignment_rgb: Optional[Any] = None,
    picked_face_trbl: Optional[_TRBL] = None,
) -> Optional[QPixmap]:
    """Load image, find matching face (or sole face), return 96x96 crop.

    picked_face_trbl + alignment_rgb: crop that box from alignment_rgb (Quick Person),
    same pixel grid as face_engine — avoids Qt vs numpy decode mismatch and similar-face
    re-match picking the wrong detection.
    """
    from exif.exif_image_loader import load_image_with_exif_correction, pil_to_qpixmap
    from faces.face_engine import face_distance, get_faces_with_locations_from_path
    from PIL import Image

    matched_loc: Optional[_TRBL] = None
    pix: Optional[QPixmap] = None

    if picked_face_trbl is not None and alignment_rgb is not None:
        matched_loc = (
            int(picked_face_trbl[0]),
            int(picked_face_trbl[1]),
            int(picked_face_trbl[2]),
            int(picked_face_trbl[3]),
        )
    else:
        pix = load_image_with_exif_correction(image_path, ignore_exif=False) or QPixmap(
            image_path
        )
        if pix.isNull() or pix.width() <= 0 or pix.height() <= 0:
            return None
        if encoding_model:
            detections = get_faces_with_locations_from_path(
                image_path, encoding_model=encoding_model
            )
        else:
            detections = get_faces_with_locations_from_path(image_path)
        if len(detections) == 1:
            matched_loc = (
                int(detections[0][0][0]),
                int(detections[0][0][1]),
                int(detections[0][0][2]),
                int(detections[0][0][3]),
            )
        else:
            best_loc = None
            best_d = None
            for loc, enc in detections:
                try:
                    d = face_distance([enc], sample_embedding)
                except Exception:
                    continue
                if d is None:
                    continue
                if best_d is None or d < best_d:
                    best_d = d
                    best_loc = loc
            if best_loc is not None and best_d is not None and best_d <= 0.6:
                matched_loc = (
                    int(best_loc[0]),
                    int(best_loc[1]),
                    int(best_loc[2]),
                    int(best_loc[3]),
                )

    if not matched_loc:
        if pix is None:
            pix = load_image_with_exif_correction(image_path, ignore_exif=False) or QPixmap(
                image_path
            )
        if pix is None or pix.isNull():
            return None
        return pix.scaled(96, 96, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)

    top, right, bottom, left = matched_loc
    pad = 10
    if alignment_rgb is not None:
        try:
            h0, w0 = int(alignment_rgb.shape[0]), int(alignment_rgb.shape[1])
            left_p = max(0, left - pad)
            top_p = max(0, top - pad)
            right_p = min(w0, right + pad)
            bottom_p = min(h0, bottom + pad)
            if right_p > left_p and bottom_p > top_p:
                pil_src = Image.fromarray(alignment_rgb)
                cropped = pil_src.crop((left_p, top_p, right_p, bottom_p))
                face_crop = pil_to_qpixmap(cropped, preserve_alpha=False)
                if face_crop is not None and not face_crop.isNull():
                    return face_crop.scaled(
                        96, 96, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation
                    )
        except Exception:
            pass

    if pix is None:
        pix = load_image_with_exif_correction(image_path, ignore_exif=False) or QPixmap(
            image_path
        )
    if pix is None or pix.isNull():
        return None
    left_p = max(0, left - pad)
    top_p = max(0, top - pad)
    right_p = min(pix.width(), right + pad)
    bottom_p = min(pix.height(), bottom + pad)
    w = max(1, right_p - left_p)
    h = max(1, bottom_p - top_p)
    face_crop = pix.copy(left_p, top_p, w, h)
    return face_crop.scaled(96, 96, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)


def ensure_face_sample_thumbnail(
    image_path: str,
    sample_embedding: List[float],
    *,
    encoding_model: Optional[str] = None,
    alignment_rgb: Optional[Any] = None,
    picked_face_trbl: Optional[_TRBL] = None,
) -> Optional[QPixmap]:
    """
    Return the same 96x96 pixmap the Faces tab uses: cache hit, else face crop + set_thumb.
    image_path may be empty if the file was deleted; then only by_face_key cache applies.
    """
    from faces.face_sample_cache import (
        embedding_to_face_key,
        get_thumb,
        get_thumb_by_face_key,
        set_thumb,
    )

    if not sample_embedding or len(sample_embedding) != 128:
        return None
    fk = embedding_to_face_key(sample_embedding)
    if not fk:
        return None
    # Read canonical `fk` first, then `fk_L` (older Quick Person wrote only `_L`). Always
    # write `fk` so Search-by-person (ensure without encoding_model) hits the same entry.
    cache_keys_read = (fk, f"{fk}_L")

    mtime = size = None
    if image_path and os.path.exists(image_path):
        try:
            st = os.stat(image_path)
            mtime, size = st.st_mtime, st.st_size
        except OSError:
            mtime, size = 0, 0
        for ck in cache_keys_read:
            px = get_thumb(image_path, mtime, size, face_key=ck)
            if px is not None and not px.isNull():
                return px

    for ck in cache_keys_read:
        px = get_thumb_by_face_key(ck)
        if px is not None and not px.isNull():
            return px

    if not image_path or not os.path.exists(image_path):
        return None

    thumb_pix = _build_face_crop_pixmap(
        image_path,
        sample_embedding,
        encoding_model=encoding_model,
        alignment_rgb=alignment_rgb,
        picked_face_trbl=picked_face_trbl,
    )
    if thumb_pix is None or thumb_pix.isNull():
        return None
    try:
        st = os.stat(image_path)
        mtime, size = st.st_mtime, st.st_size
    except OSError:
        mtime, size = 0, 0
    set_thumb(image_path, thumb_pix, mtime, size, face_key=fk)
    return thumb_pix
