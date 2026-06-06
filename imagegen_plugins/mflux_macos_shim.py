#!/usr/bin/env python3
"""Prevent mflux library subprocess calls that steal macOS focus from fullscreen Spaces."""

from __future__ import annotations

import ctypes
import ctypes.util

_APPLIED = False


def _sysctl_string(name: str) -> str:
    libc = ctypes.CDLL(ctypes.util.find_library("c"))
    key = name.encode()
    size = ctypes.c_size_t(0)
    libc.sysctlbyname(key, None, ctypes.byref(size), None, 0)
    buf = ctypes.create_string_buffer(size.value)
    libc.sysctlbyname(key, buf, ctypes.byref(size), None, 0)
    return buf.value.decode()


def apply_mflux_macos_subprocess_shim() -> None:
    """Patch mflux AppleSiliconUtil + BatterySaver before first generation."""
    global _APPLIED
    if _APPLIED:
        return

    try:
        from mflux.callbacks.instances import battery_saver as battery_mod
        from mflux.utils import apple_silicon as apple_mod
    except ImportError:
        return

    _APPLIED = True

    @classmethod
    def _get_chip_name_no_subprocess(cls) -> str:
        if cls._chip_name is not None:
            return cls._chip_name
        try:
            cls._chip_name = _sysctl_string("machdep.cpu.brand_string")
        except OSError:
            cls._chip_name = ""
        return cls._chip_name

    apple_mod.AppleSiliconUtil._get_chip_name = _get_chip_name_no_subprocess

    @classmethod
    def _is_machine_battery_powered_noop(cls) -> bool:
        return False

    battery_mod.BatterySaver._is_machine_battery_powered = _is_machine_battery_powered_noop

    def _call_before_loop_noop(self, **kwargs) -> None:
        return

    battery_mod.BatterySaver.call_before_loop = _call_before_loop_noop
