#!/usr/bin/env python3
"""Shared path exclusion helpers (cache, Photos Library, ignore directories)."""

import os


def _get_excluded_paths(config):
    """Get list of excluded paths (prowser cache, Photos Library paths, and ignore directories)"""
    cache_dir = str(config.cache_dir)
    user_home = os.path.expanduser("~")
    photos_resources = os.path.join(user_home, "Pictures", "Photos Library.photoslibrary", "resources")
    photos_scopes = os.path.join(user_home, "Pictures", "Photos Library.photoslibrary", "scopes")
    excluded = [cache_dir, photos_resources, photos_scopes]

    # Add ignore directories from settings (only enabled ones)
    try:
        settings = config.load_settings()
        ignore_dirs = settings.get('ignore_directories', [])
        if isinstance(ignore_dirs, list):
            for ignore_dir in ignore_dirs:
                if isinstance(ignore_dir, dict):
                    path = ignore_dir.get('path')
                    enabled = ignore_dir.get('enabled', False)
                    if enabled and path and isinstance(path, str) and path.strip():
                        # Expand ~ to full path before adding to excluded list
                        expanded_path = os.path.expanduser(path.strip())
                        excluded.append(expanded_path)
                elif ignore_dir and isinstance(ignore_dir, str) and ignore_dir.strip():
                    # Backward compatibility: if it's just a string, treat as enabled
                    expanded_path = os.path.expanduser(ignore_dir.strip())
                    excluded.append(expanded_path)
    except Exception:
        pass

    return excluded


def _is_excluded_path(path, excluded_paths):
    """Check if a path should be excluded"""
    try:
        path_resolved = os.path.realpath(path)
        for excl_path in excluded_paths:
            excl_resolved = os.path.realpath(excl_path)
            if path_resolved == excl_resolved or path_resolved.startswith(excl_resolved + os.sep):
                return True
    except Exception:
        pass
    return False
