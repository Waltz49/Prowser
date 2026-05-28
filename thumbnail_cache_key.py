#!/usr/bin/env python3
"""
Shared thumbnail cache key generation (single source of truth for disk filenames).
Used by ImageCacheManager and the non-Qt background worker.
"""

import hashlib
import os
import time
from typing import Dict, Optional, Tuple

# Stat cache stores: path -> (mtime_seconds_or_None, cache_monotonic_time)
StatCache = Dict[str, Tuple[Optional[int], float]]

STAT_FAILURE_CACHE_MAX_AGE = 300.0
STAT_CACHE_MAX_ENTRIES = 10000


def is_path_in_app_cache_directory(image_path: str, app_cache_dir: str) -> bool:
    """True if image_path is under the application cache directory (path-only keys, no mtime)."""
    try:
        abs_path = os.path.abspath(image_path)
        abs_cache_dir = os.path.abspath(app_cache_dir)
        return abs_path.startswith(abs_cache_dir + os.sep) or abs_path == abs_cache_dir
    except Exception:
        return False


def normalize_image_path_for_key(image_path: str) -> str:
    """Normalize path string for cache key material (matches ImageCacheManager)."""
    if image_path.startswith("/"):
        return image_path
    if image_path.startswith("~"):
        return os.path.expanduser(image_path)
    return os.path.abspath(image_path)


def _trim_stat_cache(stat_cache: StatCache) -> None:
    if len(stat_cache) > STAT_CACHE_MAX_ENTRIES:
        oldest_key = next(iter(stat_cache))
        del stat_cache[oldest_key]


def resolve_mtime_for_cache_key(
    image_path: str,
    *,
    in_app_cache: bool,
    stat_cache: StatCache,
    now: float,
    stat_cache_max_age: float,
) -> Optional[int]:
    """
    Resolve file mtime for cache key (mutates stat_cache on miss/update).
    Matches ImageCacheManager.get_cache_key stat logic.
    """
    if in_app_cache:
        return None

    mtime: Optional[int] = None
    try:
        if image_path in stat_cache:
            cached_mtime, cache_time = stat_cache[image_path]
            if cached_mtime is None:
                if now - cache_time < STAT_FAILURE_CACHE_MAX_AGE:
                    mtime = cached_mtime
                else:
                    del stat_cache[image_path]
            else:
                if now - cache_time < stat_cache_max_age:
                    mtime = cached_mtime
                else:
                    del stat_cache[image_path]

        if mtime is None:
            try:
                stat = os.stat(image_path)
                mtime = int(stat.st_mtime)
                stat_cache[image_path] = (mtime, now)
                _trim_stat_cache(stat_cache)
            except (OSError, ValueError):
                stat_cache[image_path] = (None, now)
                _trim_stat_cache(stat_cache)
    except (OSError, ValueError, TimeoutError):
        mtime = None

    return mtime


def build_key_material(path_str: str, mtime: Optional[int], ignore_exif_rotation: bool, extra: str) -> str:
    """Build the string that is hashed (before MD5)."""
    if mtime is not None:
        path_str += f"_{mtime}"
    path_str += f"_exif{int(ignore_exif_rotation)}"
    if extra:
        path_str += f"_{extra}"
    return path_str


def compute_thumbnail_cache_key(
    image_path: str,
    *,
    app_cache_dir: str,
    ignore_exif_rotation: bool,
    stat_cache: StatCache,
    now: Optional[float] = None,
    stat_cache_max_age: float = 60.0,
    extra: str = "",
) -> str:
    """
    Compute MD5 hex cache key for an image path.
    Caller must synchronize access to stat_cache when used from multiple threads.
    """
    if now is None:
        now = time.time()

    path_str = normalize_image_path_for_key(image_path)
    in_app = is_path_in_app_cache_directory(image_path, app_cache_dir)
    mtime = resolve_mtime_for_cache_key(
        image_path,
        in_app_cache=in_app,
        stat_cache=stat_cache,
        now=now,
        stat_cache_max_age=stat_cache_max_age,
    )
    material = build_key_material(path_str, mtime, ignore_exif_rotation, extra)
    return hashlib.md5(material.encode()).hexdigest()
