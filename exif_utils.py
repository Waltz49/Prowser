#!/usr/bin/env python3
"""
EXIF utilities for reading, copying, and manipulating image metadata.
Central module for EXIF processing used by screen_size_copy, convert_format,
exif_image_loader, pil_image_io, information_sidebar, map_manager, and image_browser_window.
"""

import os
from datetime import datetime
from typing import Any, Dict, Optional, Tuple

# Formats that support EXIF when saving with Pillow
EXIF_SUPPORTED_FORMATS = frozenset({'JPEG', 'PNG', 'TIFF', 'WEBP'})

# Minimum EXIF size to consider meaningful (avoids empty/minimal structures)
_MIN_EXIF_BYTES = 24

# EXIF tag IDs
TAG_ORIENTATION = 274
TAG_DATETIME = 306
TAG_DATETIME_ORIGINAL = 36867
TAG_DATETIME_DIGITIZED = 36868
TAG_GPS_INFO = 34853
TAG_USERCOMMENT = 37510  # ExifIFD.UserComment

# Date/time tag IDs in priority order
DATE_TIME_TAG_IDS = [TAG_DATETIME_ORIGINAL, TAG_DATETIME_DIGITIZED, TAG_DATETIME]

# Headings to skip past when extracting text for speak/copy (case-insensitive).
# If a line is exactly one of these (after strip), return content after that line.
USERCOMMENT_SKIP_HEADINGS = ('prompt', 'prompt:', 'description', 'description:')


def get_exif_bytes_for_piexif_from_pil(img) -> Optional[bytes]:
    """Pick raw EXIF bytes for piexif load/insert on formats with nested ExifIFD.

    ``img.info['exif']`` is often returned first by Pillow but can omit nested
    ExifIFD tags (e.g. UserComment) that appear in ``getexif().tobytes()``.
    Collect ``getexif().tobytes()`` then ``info['exif']``, and prefer any blob
    that parses under piexif and contains ExifIFD UserComment; otherwise return
    the first non-empty candidate.

    Used for JPEG/WebP UserComment delete/restore and for WebP conversion EXIF copy.
    """
    import piexif

    def _has_usercomment(b: bytes) -> bool:
        try:
            d = piexif.load(b)
            return piexif.ExifIFD.UserComment in (d.get("Exif") or {})
        except Exception:
            return False

    candidates: list[bytes] = []
    try:
        exif_obj = img.getexif()
        if exif_obj is not None and hasattr(exif_obj, "tobytes"):
            tb = exif_obj.tobytes()
            if tb:
                candidates.append(tb)
    except Exception:
        pass
    info_exif = img.info.get("exif") if img.info else None
    if info_exif:
        candidates.append(info_exif)

    for b in candidates:
        if _has_usercomment(b):
            return b
    for b in candidates:
        if b:
            return b
    return None


def get_exif_bytes_from_pil(img) -> Optional[bytes]:
    """Extract full EXIF bytes from a PIL Image for copying to another file.

    Tries img.info['exif'] first (raw bytes from file - most complete for JPEG/PNG),
    then img.getexif().tobytes() as fallback (for formats where info doesn't have it).
    For WebP, uses :func:`get_exif_bytes_for_piexif_from_pil` so nested ExifIFD (e.g.
    UserComment) is not dropped when ``info['exif']`` is incomplete.
    Returns None if no meaningful EXIF data is found.

    Works correctly for JPEG and PNG (eXIf chunk). PNG eXIf support requires Pillow 6.0+.

    Args:
        img: PIL Image object (from Image.open)

    Returns:
        Raw EXIF bytes suitable for img.save(exif=...), or None
    """
    if getattr(img, "format", None) == "WEBP":
        webp_exif = get_exif_bytes_for_piexif_from_pil(img)
        if webp_exif:
            return webp_exif

    # Primary: info['exif'] - raw bytes from file, most complete
    exif_bytes = img.info.get('exif') if img.info else None
    if exif_bytes and len(exif_bytes) >= _MIN_EXIF_BYTES:
        return exif_bytes

    # Fallback: getexif().tobytes() - for formats where info doesn't populate
    try:
        if hasattr(img, 'getexif'):
            exif_obj = img.getexif()
            if exif_obj is not None and hasattr(exif_obj, 'tobytes'):
                b = exif_obj.tobytes()
                if b and len(b) >= _MIN_EXIF_BYTES:
                    return b
    except Exception:
        pass

    return None


def get_exif_bytes_from_pil_raw(img) -> Optional[bytes]:
    """Extract raw EXIF bytes from a PIL Image without size filtering.

    Used when editing EXIF (e.g. reset/delete date) where piexif needs raw bytes.
    Returns None only when no EXIF data exists at all.

    Args:
        img: PIL Image object (from Image.open)

    Returns:
        Raw EXIF bytes, or None if no EXIF
    """
    exif_bytes = img.info.get('exif') if img.info else None
    if exif_bytes:
        return exif_bytes
    try:
        if hasattr(img, 'getexif'):
            exif_obj = img.getexif()
            if exif_obj is not None and hasattr(exif_obj, 'tobytes'):
                b = exif_obj.tobytes()
                if b:
                    return b
    except Exception:
        pass
    return None


def _exif_dict_from_pil(img) -> Optional[Dict[int, Any]]:
    """Get EXIF as dict (tag_id -> value) from PIL Image. Internal helper.
    Merges _getexif() and getexif() so HEIC and formats with partial _getexif get complete data.
    """
    result = {}
    try:
        if hasattr(img, '_getexif') and img._getexif():
            exif = img._getexif()
            if isinstance(exif, dict):
                result.update(exif)
    except Exception:
        pass
    try:
        if hasattr(img, 'getexif'):
            exif_obj = img.getexif()
            if exif_obj and len(exif_obj) > 0:
                for tag_id, value in exif_obj.items():
                    if value is not None:
                        result[tag_id] = value  # getexif overwrites (better for HEIC date fields)
    except Exception:
        pass
    return result if result else None


def get_exif_dict_from_pil(img) -> Optional[Dict[int, Any]]:
    """Extract EXIF as dict (tag_id -> value) from a PIL Image.

    Tries _getexif() first (JPEG, most formats), then getexif() (HEIC, AVIF, etc.).

    Args:
        img: PIL Image object (from Image.open)

    Returns:
        Dict mapping tag IDs to values, or None if no EXIF
    """
    return _exif_dict_from_pil(img)


def get_exif_dict_named_from_pil(img) -> Dict[str, Any]:
    """Extract EXIF as dict (tag_name -> value) from a PIL Image.

    Returns dict with human-readable tag names (e.g. 'DateTimeOriginal', 'GPSInfo').
    Returns empty dict if no EXIF.

    Args:
        img: PIL Image object (from Image.open)

    Returns:
        Dict mapping tag names to values
    """
    try:
        from PIL.ExifTags import TAGS
    except ImportError:
        return {}
    exif = _exif_dict_from_pil(img)
    if not exif:
        return {}
    return {TAGS.get(tag_id, tag_id): value for tag_id, value in exif.items() if value is not None}


def get_exif_orientation_from_pil(img) -> Optional[int]:
    """Extract EXIF orientation tag (1-8) from a PIL Image.

    Args:
        img: PIL Image object (from Image.open)

    Returns:
        Orientation value 1-8 if found, None otherwise
    """
    exif = _exif_dict_from_pil(img)
    if not exif:
        return None
    orientation = exif.get(TAG_ORIENTATION)
    return orientation if orientation and 1 <= orientation <= 8 else None


def apply_exif_orientation_to_pil(pil_img, orientation: Optional[int]):
    """Apply EXIF orientation tag (1-8) without embedded EXIF (e.g. LibRaw-decoded CR2 RGB)."""
    if orientation is None or orientation == 1:
        return pil_img
    if not isinstance(orientation, int) or not (1 <= orientation <= 8):
        return pil_img
    from PIL import Image
    methods = {
        2: Image.FLIP_LEFT_RIGHT,
        3: Image.ROTATE_180,
        4: Image.FLIP_TOP_BOTTOM,
        5: Image.TRANSPOSE,
        6: Image.ROTATE_270,
        7: Image.TRANSVERSE,
        8: Image.ROTATE_90,
    }
    method = methods.get(orientation)
    if method is None:
        return pil_img
    return pil_img.transpose(method)


def _exifread_process_file(image_path: str) -> Optional[Dict[str, Any]]:
    try:
        import exifread
        with open(image_path, 'rb') as f:
            return exifread.process_file(f, details=False)
    except Exception:
        return None


def _orientation_from_exifread_path(image_path: str) -> Optional[int]:
    tags = _exifread_process_file(image_path)
    if not tags:
        return None
    for key in ('Image Orientation', 'EXIF Orientation'):
        if key not in tags:
            continue
        t = tags[key]
        try:
            if getattr(t, 'values', None):
                v = t.values[0]
                if isinstance(v, int) and 1 <= v <= 8:
                    return v
                vi = int(v)
                if 1 <= vi <= 8:
                    return vi
        except Exception:
            pass
    return None


def _timestamp_from_exifread_path(image_path: str) -> Optional[float]:
    tags = _exifread_process_file(image_path)
    if not tags:
        return None
    for key in ('EXIF DateTimeOriginal', 'EXIF DateTimeDigitized', 'Image DateTime'):
        if key not in tags:
            continue
        try:
            s = str(tags[key].printable).strip()
            if not s:
                continue
            dt = datetime.strptime(s, "%Y:%m:%d %H:%M:%S")
            return dt.timestamp()
        except Exception:
            pass
    return None


def get_exif_dict_named_from_exifread_path(image_path: str) -> Dict[str, Any]:
    """Build a PIL-style named EXIF dict from a CR2 (or any file exifread can parse)."""
    tags = _exifread_process_file(image_path)
    if not tags:
        return {}
    from PIL.ExifTags import GPSTAGS

    out: Dict[str, Any] = {}

    def _one(tag) -> Any:
        if tag is None:
            return None
        if not getattr(tag, 'values', None):
            return str(tag.printable)
        if len(tag.values) == 1:
            return tag.values[0]
        return tag.values

    _pairs = [
        ('Image Make', 'Make'),
        ('Image Model', 'Model'),
        ('Image Software', 'Software'),
        ('Image Artist', 'Artist'),
        ('Image Copyright', 'Copyright'),
        ('Image DateTime', 'DateTime'),
        ('Image Description', 'ImageDescription'),
        ('EXIF DateTimeOriginal', 'DateTimeOriginal'),
        ('EXIF DateTimeDigitized', 'DateTimeDigitized'),
        ('EXIF ExposureTime', 'ExposureTime'),
        ('EXIF FNumber', 'FNumber'),
        ('EXIF ISOSpeedRatings', 'ISOSpeedRatings'),
        ('EXIF FocalLength', 'FocalLength'),
        ('EXIF Flash', 'Flash'),
        ('EXIF WhiteBalance', 'WhiteBalance'),
        ('EXIF MeteringMode', 'MeteringMode'),
        ('EXIF ExposureMode', 'ExposureMode'),
        ('EXIF ExposureProgram', 'ExposureProgram'),
        ('EXIF ShutterSpeedValue', 'ShutterSpeedValue'),
        ('EXIF ApertureValue', 'ApertureValue'),
        ('EXIF BrightnessValue', 'BrightnessValue'),
        ('EXIF SubjectDistance', 'SubjectDistance'),
        ('EXIF FocalLengthIn35mmFilm', 'FocalLengthIn35mmFilm'),
        ('EXIF SceneType', 'SceneType'),
        ('EXIF ColorSpace', 'ColorSpace'),
        ('EXIF LensModel', 'LensModel'),
        ('EXIF LensMake', 'LensMake'),
        ('EXIF LensType', 'LensType'),
        ('EXIF UserComment', 'UserComment'),
    ]
    for ek, name in _pairs:
        if ek in tags:
            val = _one(tags[ek])
            if val is not None:
                out[name] = val

    ori = _orientation_from_exifread_path(image_path)
    if ori is not None:
        out['Orientation'] = ori

    # GPS nested dict with integer keys (same shape as PIL _getexif GPSInfo)
    name_to_id = {v: k for k, v in GPSTAGS.items()}
    if 'GPS GPSLatitude' in tags and 'GPS GPSLongitude' in tags:
        gps_sub: Dict[int, Any] = {}

        def _dms(tag) -> Optional[Tuple[Any, Any, Any]]:
            if tag is None or not getattr(tag, 'values', None) or len(tag.values) != 3:
                return None
            return (float(tag.values[0]), float(tag.values[1]), float(tag.values[2]))

        lat = _dms(tags['GPS GPSLatitude'])
        lon = _dms(tags['GPS GPSLongitude'])
        if lat is not None and lon is not None:
            lid = name_to_id.get('GPSLatitude')
            oid = name_to_id.get('GPSLongitude')
            if lid is not None:
                gps_sub[lid] = lat
            if oid is not None:
                gps_sub[oid] = lon
            for ek, pil_name in (
                ('GPS GPSLatitudeRef', 'GPSLatitudeRef'),
                ('GPS GPSLongitudeRef', 'GPSLongitudeRef'),
            ):
                if ek in tags:
                    tid = name_to_id.get(pil_name)
                    if tid is not None:
                        gps_sub[tid] = str(tags[ek].printable).strip()
            if gps_sub:
                out['GPSInfo'] = gps_sub

    return out


def get_exif_dict_named_from_image_path(image_path: str) -> Dict[str, Any]:
    """Named EXIF dict from file path; CR2 uses exifread, others use PIL."""
    if not os.path.exists(image_path):
        return {}
    ext = os.path.splitext(image_path)[1].lower()
    if ext == '.cr2':
        return get_exif_dict_named_from_exifread_path(image_path)
    try:
        from PIL import Image
        with Image.open(image_path) as img:
            return get_exif_dict_named_from_pil(img)
    except Exception:
        return {}


def get_exif_timestamp_from_image_path(image_path: str) -> Optional[float]:
    """EXIF date/time as Unix timestamp; CR2 uses exifread, others use PIL."""
    if not os.path.exists(image_path):
        return None
    ext = os.path.splitext(image_path)[1].lower()
    if ext == '.cr2':
        ts = _timestamp_from_exifread_path(image_path)
        if ts is not None:
            return ts
    try:
        from PIL import Image
        with Image.open(image_path) as img:
            return get_exif_timestamp_from_pil(img)
    except Exception:
        return None


def get_exif_orientation_from_path(image_path: str) -> Optional[int]:
    """Extract EXIF orientation from an image file.

    Args:
        image_path: Path to the image file

    Returns:
        Orientation value 1-8 if found, None otherwise
    """
    if not os.path.exists(image_path):
        return None
    ext = os.path.splitext(image_path)[1].lower()
    if ext == '.cr2':
        o = _orientation_from_exifread_path(image_path)
        if o is not None:
            return o
    try:
        from PIL import Image
        with Image.open(image_path) as img:
            return get_exif_orientation_from_pil(img)
    except Exception:
        return None


def get_exif_timestamp_from_pil(img) -> Optional[float]:
    """Extract EXIF date/time as Unix timestamp from a PIL Image.

    Uses DateTimeOriginal, DateTimeDigitized, DateTime in that order.

    Args:
        img: PIL Image object (from Image.open)

    Returns:
        Unix timestamp, or None if no date in EXIF
    """
    exif = _exif_dict_from_pil(img)
    if not exif:
        return None
    for tag_id in DATE_TIME_TAG_IDS:
        try:
            dt_str = exif.get(tag_id)
            if dt_str and isinstance(dt_str, str):
                dt = datetime.strptime(dt_str, "%Y:%m:%d %H:%M:%S")
                return dt.timestamp()
        except Exception:
            pass
    return None


def get_gps_coords_from_pil(img) -> Optional[Tuple[float, float]]:
    """Extract GPS coordinates (latitude, longitude) from a PIL Image.

    Args:
        img: PIL Image object (from Image.open)

    Returns:
        Tuple (latitude, longitude) in decimal degrees, or None if no GPS
    """
    try:
        from PIL.ExifTags import TAGS, GPSTAGS
    except ImportError:
        return None
    exif = _exif_dict_from_pil(img)
    if not exif:
        return None
    gps_info = None
    for tag_id, value in exif.items():
        if TAGS.get(tag_id, tag_id) == 'GPSInfo':
            gps_info = value
            break
    if not gps_info or not isinstance(gps_info, dict):
        return None
    gps_data = {}
    for tag_id, value in gps_info.items():
        tag = GPSTAGS.get(tag_id, tag_id)
        gps_data[tag] = value
    lat_ref = gps_data.get('GPSLatitudeRef', 'N')
    lon_ref = gps_data.get('GPSLongitudeRef', 'E')
    lat = gps_data.get('GPSLatitude')
    lon = gps_data.get('GPSLongitude')
    if lat is None or lon is None:
        return None

    def _dms_to_decimal(dms, ref):
        if not isinstance(dms, tuple) or len(dms) != 3:
            return None
        degrees, minutes, seconds = dms
        decimal = degrees + (minutes / 60.0) + (seconds / 3600.0)
        if ref in ['S', 'W']:
            decimal = -decimal
        return decimal

    latitude = _dms_to_decimal(lat, lat_ref)
    longitude = _dms_to_decimal(lon, lon_ref)
    if latitude is None or longitude is None:
        return None
    return (latitude, longitude)


def get_gps_coords_from_path(image_path: str) -> Optional[Tuple[float, float]]:
    """Extract GPS coordinates from an image file.

    Args:
        image_path: Path to the image file

    Returns:
        Tuple (latitude, longitude) in decimal degrees, or None if no GPS
    """
    if not os.path.exists(image_path):
        return None
    ext = os.path.splitext(image_path)[1].lower()
    if ext == '.cr2':
        try:
            import exifread
            from exifread.utils import get_gps_coords
            with open(image_path, 'rb') as f:
                tags = exifread.process_file(f, details=False)
            coords = get_gps_coords(tags)
            if coords is not None:
                return float(coords[0]), float(coords[1])
        except Exception:
            pass
    try:
        from PIL import Image
        with Image.open(image_path) as img:
            return get_gps_coords_from_pil(img)
    except Exception:
        return None


def exif_orientation_to_rotation(orientation: int) -> Tuple[float, bool]:
    """Convert EXIF orientation value to rotation degrees and mirror flag.

    Args:
        orientation: EXIF orientation value (1-8)

    Returns:
        Tuple of (rotation_degrees, mirrored)
    """
    orientation_map = {
        1: (0, False),
        2: (0, True),
        3: (180, False),
        4: (180, True),
        5: (270, True),
        6: (270, False),
        7: (90, True),
        8: (90, False),
    }
    return orientation_map.get(orientation, (0, False))


def format_supports_exif(save_format: str) -> bool:
    """Return True if the given PIL save format supports EXIF."""
    return save_format.upper() in EXIF_SUPPORTED_FORMATS


def get_usercomment_from_path(file_path: str) -> Optional[bytes]:
    """Extract EXIF UserComment from an image file.

    Args:
        file_path: Path to the image file

    Returns:
        Raw UserComment bytes if present, None otherwise
    """
    if not os.path.exists(file_path):
        return None
    try:
        from PIL import Image
        with Image.open(file_path) as img:
            exif = _exif_dict_from_pil(img)
            if not exif:
                return None
            val = exif.get(TAG_USERCOMMENT)
            if val is None:
                return None
            if isinstance(val, bytes):
                return val if len(val) > 0 else None
            if isinstance(val, str):
                return val.encode('utf-8') if val else None
            return None
    except Exception:
        return None


def truncate_usercomment_before_prompt(text: str) -> str:
    """If text contains a line that exactly matches USERCOMMENT_SKIP_HEADINGS (case-insensitive),
    return only the content after that line. Otherwise return text unchanged.
    Used when reading user comment aloud or copying to speak/copy only the prompt section."""
    if not text:
        return text
    lines = text.splitlines()
    skip_set = {h.lower() for h in USERCOMMENT_SKIP_HEADINGS}
    for i, line in enumerate(lines):
        if line.strip().lower() in skip_set:
            return '\n'.join(lines[i + 1:]).strip()
    return text


def decode_usercomment(data: bytes) -> str:
    """Decode EXIF UserComment bytes to a human-readable string.

    Handles the standard 8-byte charset prefix (ASCII, UNICODE, JIS, undefined).

    Args:
        data: Raw UserComment bytes from EXIF

    Returns:
        Decoded string, empty string if data is None/empty
    """
    if not data:
        return ""
    if len(data) >= 8:
        prefix = data[:8]
        if prefix == b'ASCII\x00\x00\x00':
            return data[8:].decode('ascii', errors='replace').rstrip('\x00')
        elif prefix == b'UNICODE\x00':
            return data[8:].decode('utf-16-le', errors='replace').rstrip('\x00')
        elif prefix == b'JIS\x00\x00\x00\x00\x00':
            try:
                return data[8:].decode('iso-2022-jp', errors='replace').rstrip('\x00')
            except Exception:
                pass
        elif prefix == b'\x00\x00\x00\x00\x00\x00\x00\x00':
            text_bytes = data[8:]
        else:
            text_bytes = data
    else:
        text_bytes = data
    try:
        return text_bytes.decode('utf-8').rstrip('\x00')
    except Exception:
        return text_bytes.decode('latin-1', errors='replace').rstrip('\x00')


def encode_usercomment(text: str) -> bytes:
    """Encode a string to EXIF UserComment bytes with appropriate charset prefix.

    Uses ASCII charset prefix when possible, Unicode (UTF-16LE) prefix otherwise.

    Args:
        text: String to encode

    Returns:
        Raw UserComment bytes with charset prefix
    """
    try:
        return b'ASCII\x00\x00\x00' + text.encode('ascii')
    except UnicodeEncodeError:
        return b'UNICODE\x00' + text.encode('utf-16-le')


def restore_usercomment_to_file(file_path: str, usercomment: bytes) -> bool:
    """Restore EXIF UserComment to an image file. Preserves other EXIF data.
    Does not change the file's modification time (mtime) or access time (atime).

    Args:
        file_path: Path to the image file
        usercomment: Raw UserComment bytes to write

    Returns:
        True if successful, False otherwise
    """
    if not os.path.exists(file_path) or not usercomment:
        return False
    st = os.stat(file_path)
    file_atime, file_mtime = st.st_atime, st.st_mtime
    ext = os.path.splitext(file_path)[1].lower()
    is_jpeg = ext in ['.jpg', '.jpeg']
    is_webp = ext == '.webp'
    is_png = ext == '.png'
    is_tiff = ext in ['.tiff', '.tif']
    try:
        import piexif
        from PIL import Image
        if is_jpeg or is_webp:
            with Image.open(file_path) as img:
                exif_bytes = get_exif_bytes_for_piexif_from_pil(img)
                if exif_bytes:
                    try:
                        exif_dict = piexif.load(exif_bytes)
                    except Exception:
                        exif_dict = {"0th": {}, "Exif": {}, "GPS": {}, "1st": {}, "thumbnail": None}
                else:
                    exif_dict = {"0th": {}, "Exif": {}, "GPS": {}, "1st": {}, "thumbnail": None}
                exif_dict.setdefault("Exif", {})
                exif_dict["Exif"][piexif.ExifIFD.UserComment] = usercomment
                new_exif = piexif.dump(exif_dict)
            # File is closed - use piexif.insert for both JPEG and WebP (non-destructive, no re-encode)
            temp_path = file_path + ".tmp"
            piexif.insert(new_exif, file_path, temp_path)
            os.replace(temp_path, file_path)
            os.utime(file_path, (file_atime, file_mtime))
            return True
        elif is_png or is_tiff:
            with Image.open(file_path) as img:
                exif = img.getexif()
                if exif is None:
                    exif = {}
                exif[TAG_USERCOMMENT] = usercomment
                temp_path = file_path + ".tmp"
                if is_png:
                    img.save(temp_path, 'PNG', exif=exif)
                else:
                    img.save(temp_path, 'TIFF', exif=exif)
                os.replace(temp_path, file_path)
                os.utime(file_path, (file_atime, file_mtime))
                return True
    except Exception as e:
        print(f"DEBUG restore_usercomment_to_file: failed for {file_path}: {e}")
    return False


def delete_usercomment_from_file(file_path: str) -> bool:
    """Remove EXIF UserComment from an image file. Preserves other EXIF data.
    Does not change the file's modification time (mtime) or access time (atime).

    Args:
        file_path: Path to the image file

    Returns:
        True if successful (or if no UserComment was present), False on error
    """
    if not os.path.exists(file_path):
        return False
    st = os.stat(file_path)
    file_atime, file_mtime = st.st_atime, st.st_mtime
    ext = os.path.splitext(file_path)[1].lower()
    is_jpeg = ext in ['.jpg', '.jpeg']
    is_webp = ext == '.webp'
    is_png = ext == '.png'
    is_tiff = ext in ['.tiff', '.tif']
    success = False
    try:
        import piexif
        from PIL import Image
        if is_jpeg or is_webp:
            with Image.open(file_path) as img:
                exif_bytes = get_exif_bytes_for_piexif_from_pil(img)
                if exif_bytes:
                    try:
                        exif_dict = piexif.load(exif_bytes)
                    except Exception:
                        success = True  # No valid EXIF, nothing to delete
                    else:
                        exif_dict.setdefault("Exif", {})
                        had_usercomment = piexif.ExifIFD.UserComment in exif_dict["Exif"]
                        if had_usercomment:
                            del exif_dict["Exif"][piexif.ExifIFD.UserComment]
                            new_exif = piexif.dump(exif_dict)
                            temp_path = file_path + ".tmp"
                            piexif.insert(new_exif, file_path, temp_path)
                            os.replace(temp_path, file_path)
                            os.utime(file_path, (file_atime, file_mtime))
                            print(f"DEBUG delete_usercomment_from_file: removed UserComment from {file_path}")
                        success = True
                else:
                    success = True
        if is_webp and success and get_usercomment_from_path(file_path):
            from PIL.ExifTags import IFD

            try:
                with Image.open(file_path) as img:
                    if getattr(img, "n_frames", 1) <= 1:
                        exif = img.getexif()
                        removed = False
                        if exif is not None and len(exif) > 0:
                            try:
                                exif_ifd = exif.get_ifd(IFD.Exif)
                                if TAG_USERCOMMENT in exif_ifd:
                                    exif_ifd = dict(exif_ifd)
                                    del exif_ifd[TAG_USERCOMMENT]
                                    exif[IFD.Exif] = exif_ifd
                                    removed = True
                            except (KeyError, AttributeError):
                                pass
                            if TAG_USERCOMMENT in exif:
                                del exif[TAG_USERCOMMENT]
                                removed = True
                            if removed:
                                temp_path = file_path + ".tmp"
                                img.save(temp_path, "WEBP", exif=exif, quality=95, method=6)
                                os.replace(temp_path, file_path)
                                os.utime(file_path, (file_atime, file_mtime))
                                print(
                                    f"DEBUG delete_usercomment_from_file: WebP Pillow fallback "
                                    f"removed UserComment from {file_path}"
                                )
            except Exception as e:
                print(
                    f"DEBUG delete_usercomment_from_file: WebP Pillow fallback failed "
                    f"for {file_path}: {e}"
                )
        if is_jpeg and success and get_usercomment_from_path(file_path):
            from PIL.ExifTags import IFD

            try:
                with Image.open(file_path) as img:
                    exif = img.getexif()
                    removed = False
                    if exif is not None and len(exif) > 0:
                        try:
                            exif_ifd = exif.get_ifd(IFD.Exif)
                            if TAG_USERCOMMENT in exif_ifd:
                                exif_ifd = dict(exif_ifd)
                                del exif_ifd[TAG_USERCOMMENT]
                                exif[IFD.Exif] = exif_ifd
                                removed = True
                        except (KeyError, AttributeError):
                            pass
                        if TAG_USERCOMMENT in exif:
                            del exif[TAG_USERCOMMENT]
                            removed = True
                        if removed:
                            temp_path = file_path + ".tmp"
                            img.save(
                                temp_path,
                                "JPEG",
                                exif=exif,
                                quality=95,
                                optimize=True,
                            )
                            os.replace(temp_path, file_path)
                            os.utime(file_path, (file_atime, file_mtime))
                            print(
                                f"DEBUG delete_usercomment_from_file: JPEG Pillow fallback "
                                f"removed UserComment from {file_path}"
                            )
            except Exception as e:
                print(
                    f"DEBUG delete_usercomment_from_file: JPEG Pillow fallback failed "
                    f"for {file_path}: {e}"
                )
        elif is_png or is_tiff:
            from PIL.ExifTags import IFD
            with Image.open(file_path) as img:
                exif = img.getexif()
                removed = False
                if exif is not None and len(exif) > 0:
                    try:
                        exif_ifd = exif.get_ifd(IFD.Exif)
                        if TAG_USERCOMMENT in exif_ifd:
                            exif_ifd = dict(exif_ifd)
                            del exif_ifd[TAG_USERCOMMENT]
                            exif[IFD.Exif] = exif_ifd
                            removed = True
                    except (KeyError, AttributeError):
                        pass
                    if TAG_USERCOMMENT in exif:
                        del exif[TAG_USERCOMMENT]
                        removed = True
                    if removed:
                        temp_path = file_path + ".tmp"
                        if is_png:
                            img.save(temp_path, 'PNG', exif=exif)
                        else:
                            img.save(temp_path, 'TIFF', exif=exif)
                        os.replace(temp_path, file_path)
                        os.utime(file_path, (file_atime, file_mtime))
                        print(f"DEBUG delete_usercomment_from_file: removed UserComment from {file_path}")
                success = True
    except Exception as e:
        print(f"DEBUG delete_usercomment_from_file: failed for {file_path}: {e}")
        return False
    return success
