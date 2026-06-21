#!/usr/bin/env python3
"""Photos Library path checks without Qt (shared by utils and CNN / background worker)."""

import os


def is_inside_photos_library(path: str) -> bool:
    """
    Check if a path is within a macOS Photos Library (.photoslibrary bundle).
    """
    if not path:
        return False

    try:
        abs_path = os.path.abspath(os.path.expanduser(path))
    except Exception:
        return False

    current_path = abs_path
    while current_path and current_path != os.path.dirname(current_path):
        if current_path.endswith('.photoslibrary') or '.photoslibrary' in os.path.basename(current_path):
            if os.path.isdir(current_path) and current_path.endswith('.photoslibrary'):
                return True
        parent = os.path.dirname(current_path)
        if parent == current_path:
            break
        parent_basename = os.path.basename(parent)
        if parent_basename.endswith('.photoslibrary'):
            return True
        current_path = parent

    return False


def is_inside_photos_library_resources_or_scopes(path: str) -> bool:
    """
    Check if a path is under Photos Library resources/ or scopes/.
    """
    if not path:
        return False

    try:
        abs_path = os.path.abspath(os.path.expanduser(path))
    except Exception:
        return False

    photos_library_resources = os.path.expanduser('~/Pictures/Photos Library.photoslibrary/resources')
    try:
        photos_library_resources = os.path.abspath(photos_library_resources)
        if abs_path.startswith(photos_library_resources + os.sep) or abs_path == photos_library_resources:
            return True
    except Exception:
        pass

    photos_library_scopes = os.path.expanduser('~/Pictures/Photos Library.photoslibrary/scopes')
    try:
        photos_library_scopes = os.path.abspath(photos_library_scopes)
        if abs_path.startswith(photos_library_scopes + os.sep) or abs_path == photos_library_scopes:
            return True
    except Exception:
        pass

    return False
