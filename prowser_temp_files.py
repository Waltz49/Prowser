#!/usr/bin/env python3
"""Resolve and create Prowser temporary work directories from settings."""

from __future__ import annotations

import getpass
import os
import shutil
import tempfile
import threading
from typing import Optional

_CACHE_UNSET = object()
_cache_lock = threading.Lock()
_cached_raw: object = _CACHE_UNSET
_cached_resolved: Optional[str] = None
_verified_dirs: set[str] = set()


class TemporaryFilesDirError(OSError):
    """Raised when the configured temporary files directory cannot be created or used."""


def invalidate_temporary_files_directory_cache() -> None:
    """Clear cached resolved path (call after settings change)."""
    global _cached_raw, _cached_resolved
    with _cache_lock:
        _cached_raw = _CACHE_UNSET
        _cached_resolved = None
        _verified_dirs.clear()


def default_temporary_files_directory(user_id: Optional[str] = None) -> str:
    _ = user_id  # API compatibility; default follows active profile, not username.
    try:
        from config import get_config

        return os.path.abspath(str(get_config().prowsers_home / "tmp"))
    except Exception:
        return os.path.abspath(os.path.join(os.path.expanduser("~"), ".prowser", "tmp"))


def _normalize_path(path: str) -> str:
    return os.path.abspath(os.path.expanduser(path))


def _path_from_raw(raw: object, user_id: str) -> str:
    if raw and str(raw).strip():
        return _normalize_path(str(raw).strip())
    return default_temporary_files_directory(user_id)


def resolve_temporary_files_directory(settings: Optional[dict] = None) -> str:
    """Configured temp work dir, or default ~/.prowser/tmp when unset."""
    global _cached_raw, _cached_resolved

    if settings is not None:
        from config import get_config

        return _path_from_raw(
            settings.get("temporary_files_directory"),
            get_config().user_id,
        )

    from config import get_config

    config = get_config()
    loaded = config.load_settings()
    raw = loaded.get("temporary_files_directory")
    with _cache_lock:
        if _cached_raw == raw and _cached_resolved is not None:
            return _cached_resolved

    path = _path_from_raw(raw, config.user_id)
    with _cache_lock:
        _cached_raw = raw
        _cached_resolved = path
    return path


def _verify_writable_dir(path: str) -> None:
    if os.path.isfile(path):
        raise TemporaryFilesDirError(
            f"Temporary files path is a file, not a directory: {path}"
        )
    if not os.path.isdir(path):
        raise TemporaryFilesDirError(
            f"Temporary files directory does not exist: {path}"
        )
    probe = os.path.join(path, f".prowser_write_test_{os.getpid()}")
    try:
        fd = os.open(probe, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        return
    except PermissionError as exc:
        raise TemporaryFilesDirError(
            f"Cannot write to temporary files directory (permission denied): {path}"
        ) from exc
    except OSError as exc:
        raise TemporaryFilesDirError(
            f"Cannot write to temporary files directory: {path} ({exc})"
        ) from exc
    try:
        os.close(fd)
        os.unlink(probe)
    except OSError:
        try:
            os.close(fd)
        except OSError:
            pass
        try:
            os.unlink(probe)
        except OSError:
            pass


def _prepare_dir(path: str) -> str:
    """Create path if needed and verify writable once per process per path."""
    with _cache_lock:
        if path in _verified_dirs:
            return path
    try:
        os.makedirs(path, mode=0o700, exist_ok=True)
    except PermissionError as exc:
        raise TemporaryFilesDirError(
            f"Cannot create temporary files directory (permission denied): {path}"
        ) from exc
    except OSError as exc:
        if not os.path.isdir(path):
            raise TemporaryFilesDirError(
                f"Cannot create temporary files directory: {path} ({exc})"
            ) from exc
    _verify_writable_dir(path)
    with _cache_lock:
        _verified_dirs.add(path)
    return path


def ensure_temporary_files_directory(settings: Optional[dict] = None) -> str:
    """mkdir -p the temp work directory once per process step; raise on permission errors."""
    return _prepare_dir(resolve_temporary_files_directory(settings))


def validate_temporary_files_directory_for_settings(
    raw: Optional[str],
    user_id: Optional[str] = None,
) -> Optional[str]:
    """Return a user-facing error message, or None when the path is usable."""
    uid = user_id or getpass.getuser()
    try:
        path = _path_from_raw(raw, uid)
        if os.path.exists(path) and not os.path.isdir(path):
            return f"Temporary files path is not a directory: {path}"
        os.makedirs(path, mode=0o700, exist_ok=True)
        _verify_writable_dir(path)
        return None
    except TemporaryFilesDirError as exc:
        return str(exc)
    except OSError as exc:
        return f"Cannot use temporary files directory: {exc}"


def is_path_under_prowser_temp_dir(path: str) -> bool:
    """True when *path* lives under the configured Prowser temporary work directory."""
    if not path or not str(path).strip():
        return False
    try:
        ap = os.path.normpath(os.path.abspath(os.path.expanduser(str(path))))
    except (OSError, ValueError):
        return False
    try:
        temp_root = os.path.normpath(resolve_temporary_files_directory())
    except Exception:
        temp_root = os.path.normpath(default_temporary_files_directory())
    return ap == temp_root or ap.startswith(temp_root + os.sep)


def prowser_mkstemp_path(prefix: str = "", suffix: str = "") -> str:
    """Create a private temp file under the configured Prowser temp directory."""
    temp_dir = ensure_temporary_files_directory()
    try:
        fd, path = tempfile.mkstemp(prefix=prefix, suffix=suffix, dir=temp_dir)
    except PermissionError as exc:
        raise TemporaryFilesDirError(
            f"Cannot create temporary file (permission denied): {temp_dir}"
        ) from exc
    except OSError as exc:
        raise TemporaryFilesDirError(
            f"Cannot create temporary file in {temp_dir}: {exc}"
        ) from exc
    os.close(fd)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return path


def prowser_mkdtemp(prefix: str = "") -> str:
    """Create a private temp directory under the configured Prowser temp directory."""
    temp_dir = ensure_temporary_files_directory()
    try:
        return tempfile.mkdtemp(prefix=prefix, dir=temp_dir)
    except PermissionError as exc:
        raise TemporaryFilesDirError(
            f"Cannot create temporary directory (permission denied): {temp_dir}"
        ) from exc
    except OSError as exc:
        raise TemporaryFilesDirError(
            f"Cannot create temporary directory in {temp_dir}: {exc}"
        ) from exc


def prowser_temp_subdir(name: str) -> str:
    """Return (and create) a named subdirectory under the configured temp directory."""
    base = ensure_temporary_files_directory()
    return _prepare_dir(os.path.join(base, name))


_LEGACY_PROGRESS_PREFIX = ".imagegen-progress-"

_IMAGEGEN_TEMP_FILE_PREFIXES = (
    "imagegen-mflux-",
    "imagegen-progress-",
    "imagegen-expand-base-",
    "imagegen-mflux-infill-",
    "imagegen-mflux-infill-mask-",
    "imagegen-mflux-fill-",
    "imagegen-mflux-mask-",
)

# imagegen-infill-* batch dirs are removed explicitly via remove_persisted_pixelmator_batch;
# do not sweep them here or queued paint-infill jobs lose base/mask exports.
_IMAGEGEN_TEMP_DIR_PREFIXES = (
    "imagegen-mflux-stepwise-",
)


def remove_file_if_exists(path: str) -> None:
    if not path:
        return
    try:
        if os.path.isfile(path):
            os.unlink(path)
    except OSError:
        pass


def cleanup_exif_write_sidecar(image_path: str) -> None:
    """Remove image_path.tmp left by an interrupted EXIF UserComment write."""
    if not image_path:
        return
    remove_file_if_exists(image_path + ".tmp")


def cleanup_legacy_progress_temps_near_output(output_path: str) -> None:
    """Remove .imagegen-progress-*.png siblings left in the output directory."""
    if not output_path:
        return
    directory = os.path.dirname(os.path.abspath(output_path))
    if not directory or not os.path.isdir(directory):
        return
    try:
        for name in os.listdir(directory):
            if name.startswith(_LEGACY_PROGRESS_PREFIX) and name.endswith(".png"):
                remove_file_if_exists(os.path.join(directory, name))
    except OSError:
        pass


def cleanup_stale_imagegen_worker_temps(settings: Optional[dict] = None) -> None:
    """Sweep the configured temp dir for orphaned imagegen worker files after cancel."""
    try:
        temp_dir = resolve_temporary_files_directory(settings)
    except Exception:
        return
    if not os.path.isdir(temp_dir):
        return
    try:
        names = os.listdir(temp_dir)
    except OSError:
        return
    for name in names:
        full = os.path.join(temp_dir, name)
        if any(name.startswith(prefix) for prefix in _IMAGEGEN_TEMP_DIR_PREFIXES):
            if os.path.isdir(full):
                shutil.rmtree(full, ignore_errors=True)
            continue
        if any(name.startswith(prefix) for prefix in _IMAGEGEN_TEMP_FILE_PREFIXES):
            remove_file_if_exists(full)


def cleanup_cancelled_generation_output_artifacts(output_path: str) -> None:
    """Remove sidecar and legacy temp files next to a cancelled generation output."""
    cleanup_exif_write_sidecar(output_path)
    cleanup_legacy_progress_temps_near_output(output_path)
