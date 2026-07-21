#!/usr/bin/env python3
"""
Face engine wrapper around the face_recognition library.
Provides face detection and encoding; degrades gracefully if face_recognition is not installed.
"""

import sys
from typing import List, Optional, Any, Tuple

from thumbnails.thumbnail_constants import FACE_SCANNING_DOWNSCALE_THRESHOLD
from quick_person_search import _QUICK_PERSON_ENCODING_MODEL

# Optional: face_recognition provides face_locations, face_encodings, compare_faces, load_image_file
_face_recognition = None


# Hold as_file() contexts so returned paths stay valid (avoid temp dir cleanup)
_resource_path_holders = []


def _ensure_pkg_resources_shim():
    """Inject minimal pkg_resources shim when setuptools does not provide it (e.g. Python 3.14)."""
    if "pkg_resources" in sys.modules:
        return
    try:
        import importlib.resources
    except ImportError:
        return

    def _resource_filename_impl(package_or_requirement, resource_name):
        pkg = (
            package_or_requirement
            if isinstance(package_or_requirement, str)
            else getattr(package_or_requirement, "key", str(package_or_requirement)).replace("-", "_")
        )
        ref = importlib.resources.files(pkg) / resource_name
        try:
            cm = importlib.resources.as_file(ref)
            path = cm.__enter__()
            _resource_path_holders.append(cm)  # keep context so path stays valid
            return str(path)
        except Exception:
            return str(ref)

    class _Shim:
        resource_filename = staticmethod(_resource_filename_impl)

    sys.modules["pkg_resources"] = _Shim()


def _get_lib():
    global _face_recognition
    if _face_recognition is None:
        try:
            _ensure_pkg_resources_shim()
            import face_recognition as fr
            _face_recognition = fr
        except (ImportError, SystemExit, OSError):
            # SystemExit: face_recognition can sys.exit() if face_recognition_models missing
            pass
    return _face_recognition


def _load_image_with_exif_correction(image_path: str) -> Optional[Any]:
    """
    Load image from path with EXIF orientation correction applied.
    Returns numpy array (RGB) suitable for face_recognition, or None on error.
    Face detection and search must use orientation-corrected images so faces
    are found in the displayed orientation.
    """
    import numpy as np

    try:
        from pil_image_io import open_pil_with_exif_correction
    except ImportError:
        return None
    try:
        pil_img = open_pil_with_exif_correction(
            image_path, ignore_exif=False, cr2_half_size=False
        )
        if pil_img is None:
            return None
        if pil_img.mode != "RGB":
            pil_img = pil_img.convert("RGB")
        return np.array(pil_img)
    except Exception:
        return None


def is_available() -> bool:
    """Return True if face_recognition can be used."""
    return _get_lib() is not None


def _maybe_resize_for_detection(image: Any) -> tuple:
    """Resize image if max dimension > FACE_SCANNING_DOWNSCALE_THRESHOLD. Returns (image, scale) where scale is resized/original."""
    import numpy as np
    from PIL import Image
    h, w = image.shape[:2]
    m = max(h, w)
    if m <= FACE_SCANNING_DOWNSCALE_THRESHOLD:
        return image, 1.0
    scale = FACE_SCANNING_DOWNSCALE_THRESHOLD / m
    new_w = int(w * scale)
    new_h = int(h * scale)
    img_pil = Image.fromarray(image)
    img_pil = img_pil.resize((new_w, new_h), Image.Resampling.LANCZOS)
    return np.array(img_pil), scale


def encode_faces_from_path(image_path: str) -> List[List[float]]:
    """
    Load image from path and return list of 128-D face encodings (one per face detected).
    Respects EXIF orientation so faces are detected in the displayed orientation.
    Images larger than FACE_SCANNING_DOWNSCALE_THRESHOLD px on the longest side are resized for faster detection.
    Returns [] if library missing, no faces found, or on error.
    """
    lib = _get_lib()
    if lib is None:
        return []
    try:
        image = _load_image_with_exif_correction(image_path)
        if image is None:
            return []
        image, _ = _maybe_resize_for_detection(image)
        return encode_faces_from_image(image)
    except Exception:
        return []


def get_faces_with_locations_from_image(
    image: Any, *, encoding_model: Optional[str] = None
) -> List[tuple]:
    """
    Return face detections as a list of (location, encoding).

    `location` is in face_recognition format: (top, right, bottom, left).
    encoding_model: if set (e.g. "large"), passed to face_encodings; if None, library default.
    Returns [] if face_recognition is missing, no faces found, or on error.
    """
    lib = _get_lib()
    if lib is None:
        return []
    try:
        locations = lib.face_locations(image)
        if not locations:
            return []
        if encoding_model:
            encodings = lib.face_encodings(
                image, known_face_locations=locations, model=encoding_model
            )
        else:
            encodings = lib.face_encodings(image, known_face_locations=locations)
        results = []
        for (t, r, b, l), e in zip(locations, encodings):
            results.append(((int(t), int(r), int(b), int(l)), list(e)))
        return results
    except Exception:
        return []


def _detections_from_full_rgb(
    full_rgb: Any, *, encoding_model: Optional[str] = None
) -> List[tuple]:
    """Detect on a downscaled working copy; locations are scaled back to full_rgb pixel coordinates."""
    image, scale = _maybe_resize_for_detection(full_rgb)
    results = get_faces_with_locations_from_image(image, encoding_model=encoding_model)
    if scale != 1.0 and results:
        inv = 1.0 / scale
        results = [
            ((int(t * inv), int(r * inv), int(b * inv), int(l * inv)), enc)
            for (t, r, b, l), enc in results
        ]
    return results


def get_faces_with_locations_and_rgb_from_path(
    image_path: str, *, encoding_model: Optional[str] = None
) -> Tuple[List[tuple], Optional[Any]]:
    """
    One file load: return (detections, rgb_numpy) where rgb_numpy is HxWx3 uint8 in the same
    coordinate system as detection boxes. Build the picker preview from this array (e.g. via
    PIL + pil_to_qpixmap) so the icon matches encodings without a second decode path.
    """
    lib = _get_lib()
    if lib is None:
        return [], None
    try:
        full_rgb = _load_image_with_exif_correction(image_path)
        if full_rgb is None:
            return [], None
        results = _detections_from_full_rgb(full_rgb, encoding_model=encoding_model)
        return results, full_rgb
    except Exception:
        return [], None


def get_faces_with_locations_from_path(
    image_path: str, *, encoding_model: Optional[str] = _QUICK_PERSON_ENCODING_MODEL
) -> List[tuple]:
    """
    Load image from path and return list of (location, encoding).
    Respects EXIF orientation so faces are detected in the displayed orientation.

    `location` is in face_recognition format: (top, right, bottom, left), in original image coordinates.
    Images larger than 2000px on longest side are resized for faster detection; locations are scaled back.
    encoding_model: optional model name for encodings (e.g. "large" to match get_largest_face_encoding_from_path).
    Returns [] if library missing, no faces found, or on error.
    """
    dets, _rgb = get_faces_with_locations_and_rgb_from_path(
        image_path, encoding_model=encoding_model
    )
    return dets


def encode_faces_from_image(image: Any) -> List[List[float]]:
    """
    Given an image (numpy array, RGB), return list of 128-D face encodings.
    Returns [] if library missing, no faces, or error.
    """
    lib = _get_lib()
    if lib is None:
        return []
    try:
        locations = lib.face_locations(image)
        if not locations:
            return []
        encodings = lib.face_encodings(image, known_face_locations=locations, model="large")
        return [list(e) for e in encodings]
    except Exception:
        return []


def compare_faces(known_encodings: List[List[float]], unknown_encoding: List[float], tolerance: float = 0.6) -> bool:
    """
    Return True if unknown_encoding matches any of known_encodings within tolerance.
    If face_recognition is not available, returns False.
    """
    lib = _get_lib()
    if lib is None or not known_encodings or not unknown_encoding:
        return False
    try:
        import numpy as np
        known = [np.array(e, dtype=float) for e in known_encodings]
        unknown = np.array(unknown_encoding, dtype=float)
        results = lib.compare_faces(known, unknown, tolerance=tolerance)
        return any(results)
    except Exception:
        return False


def face_distance(known_encodings: List[List[float]], unknown_encoding: List[float]) -> Optional[float]:
    """
    Return the minimum Euclidean distance from unknown_encoding to any of known_encodings.
    Lower distance = closer match. Returns None if face_recognition is not available.
    """
    lib = _get_lib()
    if lib is None or not known_encodings or not unknown_encoding:
        return None
    try:
        import numpy as np
        known = [np.array(e, dtype=float) for e in known_encodings]
        unknown = np.array(unknown_encoding, dtype=float)
        distances = lib.face_distance(known, unknown)
        return float(np.min(distances))
    except Exception:
        return None


def face_mean_distance(known_encodings: List[List[float]], unknown_encoding: List[float]) -> Optional[float]:
    """
    Mean Euclidean distance from unknown_encoding to each of known_encodings (same metric as face_distance).
    Person search ranks by this so matches account for all stored samples, not only the closest one.
    Returns None if face_recognition is not available.
    """
    lib = _get_lib()
    if lib is None or not known_encodings or not unknown_encoding:
        return None
    try:
        import numpy as np
        known = [np.array(e, dtype=float) for e in known_encodings]
        unknown = np.array(unknown_encoding, dtype=float)
        distances = lib.face_distance(known, unknown)
        return float(np.mean(distances))
    except Exception:
        return None


