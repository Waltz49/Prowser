#!/usr/bin/env python3
"""Single-instance lock and fast named-pipe forwarding for Prowser."""

from __future__ import annotations

import errno
import fcntl
import json
import os
import time
from typing import Any, Dict, Optional

_lock_fd: Optional[int] = None


def acquire_primary_instance_lock(lock_path: str) -> bool:
    """Try to become the primary instance. Returns True if lock acquired."""
    global _lock_fd

    os.makedirs(os.path.dirname(lock_path), exist_ok=True)
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except (BlockingIOError, OSError):
        os.close(fd)
        return False

    os.ftruncate(fd, 0)
    os.write(fd, f"{os.getpid()}\n".encode())
    _lock_fd = fd
    return True


def _try_write_pipe_once(pipe_path: str, payload: bytes) -> bool:
    if not os.path.exists(pipe_path):
        return False

    try:
        fd = os.open(pipe_path, os.O_WRONLY | os.O_NONBLOCK)
    except OSError as exc:
        if exc.errno in (errno.ENXIO, errno.ENOENT):
            return False
        return False

    try:
        os.write(fd, payload)
        return True
    except OSError:
        return False
    finally:
        os.close(fd)


def forward_message_to_running_instance(
    message: Dict[str, Any],
    pipe_path: str,
    *,
    retries: int = 6,
    retry_delay: float = 0.05,
    deadline: Optional[float] = None,
) -> bool:
    """Send JSON config to a running instance via named pipe (non-blocking)."""
    payload = (json.dumps(message) + "\n").encode("utf-8")
    end_time = (time.time() + deadline) if deadline is not None else None
    attempt = 0
    while True:
        if _try_write_pipe_once(pipe_path, payload):
            return True
        attempt += 1
        if end_time is not None:
            if time.time() >= end_time:
                return False
        elif attempt >= retries:
            return False
        time.sleep(retry_delay)
