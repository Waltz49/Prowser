#!/usr/bin/env python3
"""Granular image-generation timing lines for Tools > Debug > View log."""

from __future__ import annotations

import time
from typing import Any, Optional

from debug_log import debug_timestamp

_perf_debug = False


def set_perf_debug(enabled: bool) -> None:
    global _perf_debug
    _perf_debug = bool(enabled)


def perf_debug_enabled() -> bool:
    return _perf_debug


def perf_log(message: str) -> None:
    if _perf_debug:
        print(f"{debug_timestamp()} [imagegen-perf] {message}", flush=True)


def perf_log_kv(event: str, **fields: Any) -> None:
    if not _perf_debug:
        return
    parts = [event]
    for key, value in fields.items():
        if value is None:
            continue
        if isinstance(value, float):
            parts.append(f"{key}={value:.3f}s")
        else:
            parts.append(f"{key}={value}")
    perf_log(" ".join(parts))


class PerfTimer:
    """Context manager: logs elapsed on exit when perf debug is on."""

    def __init__(self, event: str, **fields: Any) -> None:
        self._event = event
        self._fields = dict(fields)
        self._t0: Optional[float] = None

    def __enter__(self) -> PerfTimer:
        self._t0 = time.perf_counter()
        perf_log_kv(f"{self._event}_start", **self._fields)
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._t0 is None:
            return
        elapsed = time.perf_counter() - self._t0
        status = "error" if exc is not None else "ok"
        perf_log_kv(
            self._event,
            elapsed=elapsed,
            status=status,
            **self._fields,
        )
