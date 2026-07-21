#!/usr/bin/env python3
"""
Beachball Fix for Image Browser
This module implements fixes for the beachball issue caused by concurrent refresh operations.
"""

from threading import Lock

from PySide6.QtCore import QMutex, QMutexLocker, QTimer

# Global refresh lock to prevent concurrent refresh operations
_global_refresh_lock = QMutex()
_global_refresh_in_progress = False
_refresh_queue = []
_refresh_queue_mutex = QMutex()


def acquire_refresh_lock(timeout_ms: int = 100) -> bool:
    """
    Try to acquire the global refresh lock with a timeout.
    Returns True if lock was acquired, False otherwise.
    """
    global _global_refresh_in_progress

    if _global_refresh_lock.tryLock(timeout_ms):
        _global_refresh_in_progress = True
        return True

    return False


def release_refresh_lock():
    """Release the global refresh lock and reset the flag."""
    global _global_refresh_in_progress

    _global_refresh_in_progress = False
    _global_refresh_lock.unlock()


def is_refresh_in_progress() -> bool:
    """Check if a refresh operation is currently in progress."""
    return _global_refresh_in_progress


def queue_refresh_operation(operation_func, *args, **kwargs):
    """
    Queue a refresh operation to be executed when the current one completes.
    This prevents multiple concurrent refresh operations from interfering with each other.
    """
    global _refresh_queue

    with QMutexLocker(_refresh_queue_mutex):
        _refresh_queue.append((operation_func, args, kwargs))

    QTimer.singleShot(50, process_refresh_queue)


def process_refresh_queue():
    """Process any queued refresh operations."""
    global _refresh_queue

    if is_refresh_in_progress():
        QTimer.singleShot(100, process_refresh_queue)
        return

    with QMutexLocker(_refresh_queue_mutex):
        if not _refresh_queue:
            return
        operation_func, args, kwargs = _refresh_queue.pop(0)

    try:
        operation_func(*args, **kwargs)
    except Exception:
        pass

    with QMutexLocker(_refresh_queue_mutex):
        has_more = bool(_refresh_queue)
    if has_more:
        QTimer.singleShot(10, process_refresh_queue)


def safe_refresh_wrapper(func):
    """
    Decorator to make refresh operations thread-safe.
    If a refresh is already in progress, the operation is queued.
    """
    def wrapper(*args, **kwargs):
        if acquire_refresh_lock():
            try:
                return func(*args, **kwargs)
            finally:
                release_refresh_lock()
        queue_refresh_operation(func, *args, **kwargs)
        return None
    return wrapper


_thumbnail_lock = Lock()
_thumbnail_queue = []


def acquire_thumbnail_lock():
    """Try to acquire the thumbnail operation lock. Return True if acquired, False otherwise."""
    return _thumbnail_lock.acquire(blocking=False)


def release_thumbnail_lock():
    """Release the thumbnail operation lock."""
    if _thumbnail_lock.locked():
        _thumbnail_lock.release()


def queue_thumbnail_operation(func, *args, **kwargs):
    """Queue a thumbnail operation for later execution."""
    _thumbnail_queue.append((func, args, kwargs))
    if len(_thumbnail_queue) == 1:
        QTimer.singleShot(0, process_thumbnail_queue)


def process_thumbnail_queue():
    """Process queued thumbnail operations."""
    if not _thumbnail_queue:
        return

    if not acquire_thumbnail_lock():
        QTimer.singleShot(5, process_thumbnail_queue)
        return

    try:
        func, args, kwargs = _thumbnail_queue.pop(0)
        try:
            func(*args, **kwargs)
        except Exception:
            pass
    finally:
        release_thumbnail_lock()

    if _thumbnail_queue:
        QTimer.singleShot(0, process_thumbnail_queue)


def safe_thumbnail_wrapper(func):
    """
    Decorator to make thumbnail operations thread-safe.
    If a thumbnail operation is already in progress, the operation is queued.
    """
    def wrapper(*args, **kwargs):
        if acquire_thumbnail_lock():
            try:
                return func(*args, **kwargs)
            finally:
                release_thumbnail_lock()
        queue_thumbnail_operation(func, *args, **kwargs)
        return None
    return wrapper


_generate_lock = Lock()
_generate_queue = []


def acquire_generate_lock():
    """Try to acquire the generate operation lock. Returns True if acquired."""
    return _generate_lock.acquire(blocking=False)


def release_generate_lock():
    """Release the generate operation lock."""
    if _generate_lock.locked():
        _generate_lock.release()



def process_generate_queue():
    """Process queued generate operations."""
    if not _generate_queue:
        return

    if not acquire_generate_lock():
        QTimer.singleShot(5, process_generate_queue)
        return

    try:
        func, args, kwargs = _generate_queue.pop(0)
        try:
            func(*args, **kwargs)
        except Exception:
            pass
    finally:
        release_generate_lock()

    if _generate_queue:
        QTimer.singleShot(0, process_generate_queue)


