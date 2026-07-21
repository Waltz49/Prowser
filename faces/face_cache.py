#!/usr/bin/env python3
"""
Face cache: per-image face embeddings under ~/.prowser/cache/image_recognition/face_cache/.
Index file maps image path -> mtime/size/md5; data files store list of 128-D encodings per image.
MD5 used for content-based invalidation (policy B: validated during scan only).
Thread-safe for file I/O.

The index is kept in memory after first load; lookups do not re-read index.json per file.

Path keys: normalize_path_for_face_cache() resolves to a canonical real path for cache identity.
For user-visible strings (menus, errors), use utils.normalize_path_for_display instead — different
contract; do not mix them when passing paths into face_cache APIs.
"""

import json
import hashlib
import os
import threading
from pathlib import Path
from typing import List, Optional, Dict, Any

_lock = threading.Lock()

# None = not loaded yet; dict is the live index (same object mutated until reload).
_index_memory: Optional[Dict[str, Any]] = None

# Persist index.json at most once per N set_encodings calls; call flush_face_cache_index() to force.
INDEX_PERSIST_INTERVAL = 50
_index_writes_since_persist: int = 0


def _compute_file_md5(path: str) -> Optional[str]:
    """Compute MD5 of file contents. Returns None on error."""
    try:
        h = hashlib.md5()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()
    except (OSError, IOError):
        return None


def _get_cache_dir() -> Path:
    from config import get_config
    d = get_config().image_recognition_cache_dir / "face_cache"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _path_key(path: str) -> str:
    return str(Path(path).resolve())


def normalize_path_for_face_cache(path: str) -> str:
    """Canonical resolved path for face cache keys and scan identity (not for UI display).

    Use for every path passed to face_cache, run_scan, or face-keyed lookups.
    """
    try:
        return _path_key(path)
    except (OSError, ValueError):
        return path


def _candidate_index_keys(path: str) -> List[str]:
    """
    Possible index.json key strings for the same file (join() vs scandir vs /Volumes/... quirks).
    Writes use _path_key(); lookups must try all variants so cache hits after mass rename.
    """
    keys: List[str] = []
    try:
        k1 = str(Path(path).resolve())
        keys.append(k1)
    except (OSError, ValueError):
        pass
    try:
        k2 = os.path.normpath(os.path.realpath(path))
        if k2 not in keys:
            keys.append(k2)
    except (OSError, ValueError):
        pass
    return keys


def _data_path_for_index_key(index_key: str) -> Path:
    """Payload JSON path for a key exactly as stored in index (same as _path_hash(_path_key(p)) when key == _path_key(p))."""
    return _get_cache_dir() / "data" / f"{_path_hash(index_key)}.json"


def _path_hash(path: str) -> str:
    return hashlib.sha256(path.encode("utf-8")).hexdigest()[:24]


def _index_path() -> Path:
    return _get_cache_dir() / "index.json"


def _data_path(path: str) -> Path:
    return _get_cache_dir() / "data" / f"{_path_hash(_path_key(path))}.json"


def _load_index_into_memory() -> Dict[str, Any]:
    """Load index.json into _index_memory (call only with _lock held)."""
    global _index_memory
    idx_path = _index_path()
    if not idx_path.exists():
        _index_memory = {}
        return _index_memory
    try:
        with open(idx_path, "r", encoding="utf-8") as f:
            loaded = json.load(f)
        _index_memory = loaded if isinstance(loaded, dict) else {}
    except (json.JSONDecodeError, IOError):
        _index_memory = {}
    return _index_memory


def _get_index() -> Dict[str, Any]:
    """Return the in-memory index, loading from disk on first use (call only with _lock held)."""
    global _index_memory
    if _index_memory is None:
        return _load_index_into_memory()
    return _index_memory


def _persist_index(index: Dict[str, Any]) -> None:
    """Write index dict to disk (call only with _lock held)."""
    global _index_writes_since_persist
    idx_path = _index_path()
    _get_cache_dir()
    with open(idx_path, "w", encoding="utf-8") as f:
        json.dump(index, f, indent=0)
    _index_writes_since_persist = 0


def flush_face_cache_index() -> None:
    """Write index to disk if there are batched set_encodings since last persist."""
    global _index_writes_since_persist
    with _lock:
        if _index_writes_since_persist == 0:
            return
        index = _get_index()
        _persist_index(index)


def persist_face_cache_index_always() -> None:
    """Write the in-memory face index to disk regardless of batch counter (e.g. after mass rename)."""
    with _lock:
        index = _get_index()
        _persist_index(index)


def get_encodings(image_path: str, mtime: Optional[float] = None, size: Optional[int] = None) -> Optional[List[List[float]]]:
    """
    Return list of face encodings (128-D each) for image_path if cached and still valid.
    If mtime/size are provided, only return cache if they match; otherwise use stored metadata.
    Returns None if not cached or invalid.
    """
    with _lock:
        index = _get_index()
        entry = None
        matched_key = None
        for cand in _candidate_index_keys(image_path):
            entry = index.get(cand)
            if entry is not None:
                matched_key = cand
                break
        if not entry:
            return None
        if mtime is not None and entry.get("mtime") != mtime:
            return None
        if size is not None and entry.get("size") != size:
            return None
        data_path = _data_path_for_index_key(matched_key) if matched_key else _data_path(image_path)
        if not data_path.exists():
            return None
        dp = data_path
    try:
        with open(dp, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, IOError):
        return None
    encodings = data.get("encodings")
    if not isinstance(encodings, list):
        return None
    return encodings


def set_encodings(image_path: str, encodings: List[List[float]], mtime: Optional[float] = None, size: Optional[int] = None) -> None:
    """Store face encodings for image_path. mtime/size/md5 stored for content-based invalidation."""
    key = _path_key(image_path)
    if mtime is None or size is None:
        try:
            st = os.stat(image_path)
            mtime = st.st_mtime
            size = st.st_size
        except OSError:
            mtime = 0
            size = 0
    md5_val = _compute_file_md5(image_path)
    data_dir = _get_cache_dir() / "data"
    data_dir.mkdir(exist_ok=True)
    data_path = _data_path(image_path)
    with open(data_path, "w", encoding="utf-8") as f:
        json.dump({"encodings": encodings}, f, indent=0)
    with _lock:
        global _index_writes_since_persist
        index = _get_index()
        entry: Dict[str, Any] = {"mtime": mtime, "size": size}
        if md5_val:
            entry["md5"] = md5_val
        index[key] = entry
        _index_writes_since_persist += 1
        if _index_writes_since_persist >= INDEX_PERSIST_INTERVAL:
            _persist_index(index)


def clear_face_cache_for_directory(directory_path: str) -> int:
    """
    Remove face cache entries for images under directory_path (non-recursive: only direct children).
    Returns the number of entries removed.
    """
    try:
        dir_resolved = str(Path(directory_path).resolve())
        if not dir_resolved.endswith(os.sep):
            dir_resolved += os.sep
    except (OSError, ValueError):
        return 0
    removed = 0
    with _lock:
        index = _get_index()
        if not index and not _index_path().exists():
            return 0
        if not isinstance(index, dict):
            return 0
        paths_to_remove = []
        for path in list(index.keys()):
            try:
                normalized = str(Path(path).resolve())
                if normalized.startswith(dir_resolved):
                    remainder = normalized[len(dir_resolved):]
                    if os.sep not in remainder and "/" not in remainder:
                        paths_to_remove.append(path)
            except (OSError, ValueError):
                pass
        for path in paths_to_remove:
            index.pop(path, None)
            data_path = _data_path(path)
            try:
                if data_path.exists():
                    data_path.unlink()
            except OSError:
                pass
            removed += 1
        if paths_to_remove:
            _persist_index(index)
    return removed


def scrub_stale_entries() -> int:
    """
    Remove face cache entries for images that no longer exist.
    Returns the number of entries removed.
    """
    with _lock:
        index = _get_index()
        if not index and not _index_path().exists():
            return 0
        if not isinstance(index, dict):
            return 0
        paths_to_remove = []
        for path in list(index.keys()):
            try:
                normalized_path = str(Path(path).resolve())
                if not os.path.exists(normalized_path):
                    paths_to_remove.append(path)
            except (OSError, ValueError):
                paths_to_remove.append(path)
        for path in paths_to_remove:
            index.pop(path, None)
            data_path = _data_path(path)
            try:
                if data_path.exists():
                    data_path.unlink()
            except OSError:
                pass
        if paths_to_remove:
            _persist_index(index)
        return len(paths_to_remove)



def _mtime_matches_index(st_mtime: float, index_mtime) -> bool:
    """True if on-disk mtime matches index (exact or within tolerance for JSON/fs float noise)."""
    if index_mtime is None:
        return False
    try:
        return st_mtime == index_mtime or abs(st_mtime - float(index_mtime)) < 1e-4
    except (TypeError, ValueError):
        return False


def _refresh_index_stat_for_key(cache_key: str, st: os.stat_result) -> None:
    """Update index mtime/size after content verified (call only with _lock)."""
    global _index_writes_since_persist
    idx = _get_index()
    e = idx.get(cache_key)
    if e is None:
        return
    e["mtime"] = st.st_mtime
    e["size"] = st.st_size
    _index_writes_since_persist += 1
    if _index_writes_since_persist >= INDEX_PERSIST_INTERVAL:
        _persist_index(idx)


def has_cached_faces(image_path: str) -> bool:
    """Return True if image_path has cached face encodings and file unchanged.

    With md5 in index: mtime may use a small float tolerance; if mtime still mismatches, md5 can
    salvage the entry and refresh stored mtime/size (same file content, metadata drift).

    Legacy entries (no md5): require exact mtime and size match.
    """
    with _lock:
        index = _get_index()
        entry = None
        key = None
        for cand in _candidate_index_keys(image_path):
            entry = index.get(cand)
            if entry is not None:
                key = cand
                break
        if not entry or key is None:
            return False
        data_path = _data_path_for_index_key(key)
        if not data_path.exists():
            return False
    try:
        st = os.stat(image_path)
    except OSError:
        return False
    es = entry.get("size")
    stored_md5 = entry.get("md5")
    if st.st_size != es:
        if stored_md5:
            cur_md5 = _compute_file_md5(image_path)
            if cur_md5 == stored_md5:
                with _lock:
                    _refresh_index_stat_for_key(key, st)
                return True
        return False
    em = entry.get("mtime")
    if stored_md5:
        if _mtime_matches_index(st.st_mtime, em):
            return True
        cur_md5 = _compute_file_md5(image_path)
        if cur_md5 == stored_md5:
            with _lock:
                _refresh_index_stat_for_key(key, st)
            return True
        return False
    if st.st_mtime == em:
        return True
    return False
