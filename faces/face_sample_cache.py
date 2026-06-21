#!/usr/bin/env python3
"""
Face sample thumbnail cache: 96x96 face crop thumbnails for known-faces UI.
Stored under ~/.prowser/cache/image_recognition/face_cache/sample_thumbs/.
Index maps path (or path+face_key) -> mtime/size; images stored as PNG.
When face_key is provided, cache key includes it so the same image can store
different face crops for different people. Invalidated when source file changes.
Also stores thumbnails by face_key alone (by_face_key/) so samples persist when
the original source image is deleted. Thread-safe for file I/O.
"""

import hashlib
import json
import os
import shutil
import struct
import threading
from pathlib import Path
from typing import List, Optional, Tuple

from PySide6.QtGui import QImage, QPixmap

_lock = threading.Lock()


def embedding_to_face_key(embedding: List[float]) -> Optional[str]:
    """Return a stable hash for a 128-D face embedding, or None if invalid."""
    if not embedding or len(embedding) != 128:
        return None
    try:
        return hashlib.sha256(struct.pack("128d", *embedding)).hexdigest()[:16]
    except (struct.error, TypeError):
        return None


def _get_cache_dir() -> Path:
    from config import get_config
    d = get_config().image_recognition_cache_dir / "face_cache" / "sample_thumbs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _path_key(path: str) -> str:
    return str(Path(path).resolve())


def _path_hash(path: str) -> str:
    return hashlib.sha256(path.encode("utf-8")).hexdigest()[:24]


def _index_path() -> Path:
    return _get_cache_dir() / "index.json"


def _images_dir() -> Path:
    d = _get_cache_dir() / "images"
    d.mkdir(exist_ok=True)
    return d


def _by_face_key_dir() -> Path:
    """Path-independent storage: thumbnails keyed by face_key only."""
    d = _get_cache_dir() / "by_face_key"
    d.mkdir(exist_ok=True)
    return d


def _index_key(path: str, face_key: Optional[str]) -> str:
    """Composite key: path+face_key when face_key given, else path only (legacy)."""
    pk = _path_key(path)
    if face_key:
        return f"{pk}::{face_key}"
    return pk


def _thumb_path(path: str, face_key: Optional[str] = None) -> Path:
    return _images_dir() / f"{_path_hash(_index_key(path, face_key))}.png"


def get_thumb(
    image_path: str,
    mtime: Optional[float] = None,
    size: Optional[int] = None,
    face_key: Optional[str] = None,
) -> Optional[QPixmap]:
    """
    Return cached 96x96 face thumbnail for image_path if cached and still valid.
    face_key: when provided, distinguishes different faces in the same image.
    If mtime/size are provided, only return cache if they match; otherwise use stored metadata.
    Returns None if not cached or invalid.
    """
    key = _index_key(image_path, face_key)
    idx_path = _index_path()
    with _lock:
        if not idx_path.exists():
            return None
        try:
            with open(idx_path, "r", encoding="utf-8") as f:
                index = json.load(f)
        except (json.JSONDecodeError, IOError):
            return None
        entry = index.get(key)
        if not entry:
            return None
        if mtime is not None and entry.get("mtime") != mtime:
            return None
        if size is not None and entry.get("size") != size:
            return None
        thumb_path = _thumb_path(image_path, face_key)
        if not thumb_path.exists():
            return None
    try:
        img = QImage(str(thumb_path))
        if img.isNull():
            return None
        return QPixmap.fromImage(img)
    except Exception:
        return None


def get_thumb_by_face_key(face_key: Optional[str]) -> Optional[QPixmap]:
    """
    Return cached 96x96 face thumbnail by face_key only. Path-independent;
    works when the original source image has been deleted.
    """
    if not face_key:
        return None
    thumb_path = _by_face_key_dir() / f"{face_key}.png"
    with _lock:
        if not thumb_path.exists():
            return None
    try:
        img = QImage(str(thumb_path))
        if img.isNull():
            return None
        return QPixmap.fromImage(img)
    except Exception:
        return None


def set_thumb_by_face_key(face_key: Optional[str], pixmap: QPixmap) -> None:
    """Store 96x96 face thumbnail by face_key only. Path-independent persistence."""
    if pixmap.isNull() or not face_key:
        return
    thumb_path = _by_face_key_dir() / f"{face_key}.png"
    img = pixmap.toImage()
    if img.isNull():
        return
    with _lock:
        try:
            img.save(str(thumb_path), "PNG")
        except Exception:
            pass


def set_thumb(
    image_path: str,
    pixmap: QPixmap,
    mtime: Optional[float] = None,
    size: Optional[int] = None,
    face_key: Optional[str] = None,
) -> None:
    """Store 96x96 face thumbnail for image_path. face_key distinguishes faces in same image.
    When face_key is provided, also stores a path-independent copy for when source is deleted."""
    if pixmap.isNull():
        return
    key = _index_key(image_path, face_key)
    if mtime is None or size is None:
        try:
            st = os.stat(image_path)
            mtime = st.st_mtime
            size = st.st_size
        except OSError:
            mtime = 0
            size = 0
    thumb_path = _thumb_path(image_path, face_key)
    idx_path = _index_path()
    # Save image to disk
    img = pixmap.toImage()
    if img.isNull():
        return
    with _lock:
        try:
            img.save(str(thumb_path), "PNG")
        except Exception:
            return
        index = {}
        if idx_path.exists():
            try:
                with open(idx_path, "r", encoding="utf-8") as f:
                    index = json.load(f)
            except (json.JSONDecodeError, IOError):
                pass
        index[key] = {"mtime": mtime, "size": size}
        with open(idx_path, "w", encoding="utf-8") as f:
            json.dump(index, f, indent=0)
    # Path-independent copy: persists when source image is deleted
    if face_key:
        set_thumb_by_face_key(face_key, pixmap)


def migrate_path_in_index(old_path: str, new_path: str) -> int:
    """
    Move sample thumb index entries and PNG files from old_path to new_path.
    Handles legacy path-only keys and composite path::face_key keys.
    Updates stored mtime/size to match new_path on disk.
    Returns the number of index entries migrated.
    """
    try:
        old_pk = _path_key(old_path)
        new_pk = _path_key(new_path)
    except (OSError, ValueError):
        return 0
    if old_pk == new_pk:
        return 0
    try:
        st = os.stat(new_path)
        new_mtime, new_size = st.st_mtime, st.st_size
    except OSError:
        return 0
    idx_path = _index_path()
    migrated = 0
    index_changed = False
    with _lock:
        if not idx_path.exists():
            return 0
        try:
            with open(idx_path, "r", encoding="utf-8") as f:
                index = json.load(f)
        except (json.JSONDecodeError, IOError):
            return 0
        if not isinstance(index, dict):
            return 0
        to_process: List[Tuple[str, Optional[str]]] = []
        for k in list(index.keys()):
            if not isinstance(k, str):
                continue
            if k == old_pk:
                to_process.append((k, None))
            elif k.startswith(old_pk + "::"):
                to_process.append((k, k[len(old_pk) + 2 :]))
        for old_key, face_key in to_process:
            if old_key not in index:
                continue
            old_thumb = _images_dir() / f"{_path_hash(old_key)}.png"
            new_idx_key = _index_key(new_path, face_key)
            if not old_thumb.exists():
                del index[old_key]
                index_changed = True
                continue
            new_thumb = _thumb_path(new_path, face_key)
            try:
                _images_dir().mkdir(parents=True, exist_ok=True)
                shutil.copy2(old_thumb, new_thumb)
                try:
                    old_thumb.unlink()
                except OSError:
                    pass
            except OSError:
                continue
            del index[old_key]
            index[new_idx_key] = {"mtime": new_mtime, "size": new_size}
            migrated += 1
            index_changed = True
        if index_changed:
            try:
                with open(idx_path, "w", encoding="utf-8") as f:
                    json.dump(index, f, indent=0)
            except OSError:
                return 0
    return migrated


def clear_all() -> int:
    """
    Remove all face sample thumbnails and index.
    Returns the number of image files removed.
    """
    idx_path = _index_path()
    images_dir = _images_dir()
    by_fk_dir = _by_face_key_dir()
    count = 0
    with _lock:
        if images_dir.exists():
            for p in images_dir.glob("*.png"):
                try:
                    p.unlink()
                    count += 1
                except OSError:
                    pass
        if by_fk_dir.exists():
            for p in by_fk_dir.glob("*.png"):
                try:
                    p.unlink()
                    count += 1
                except OSError:
                    pass
        if idx_path.exists():
            try:
                idx_path.unlink()
            except OSError:
                pass
    return count
