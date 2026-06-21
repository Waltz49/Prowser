#!/usr/bin/env python3
"""Merge analyzer output with mandatory/min/full PyInstaller directives for the build script."""

from __future__ import annotations

import json
import os
import sys

from pyinstaller_optional_packages import (
    ALWAYS_EXCLUDE_IMPORT_ROOTS,
    FULL_BUILD_COLLECT_ALL,
    FULL_BUILD_EXTRA_HIDDEN,
    FULL_EXTRA_COLLECT_SUBMODULES,
    FULL_SPEC_COLLECT_PACKAGES,
    FULL_SPEC_COPY_METADATA,
    MANDATORY_HIDDEN,
    MANDATORY_PYOBJC_HIDDEN,
    MIN_BUILD_COLLECT_ALL,
    MIN_BUILD_EXTRA_HIDDEN,
    MIN_EXCLUDE_MODULES,
    MIN_EXTRA_COLLECT_SUBMODULES,
    MIN_SPEC_COLLECT_PACKAGES,
    MIN_SPEC_COPY_METADATA,
    filter_hidden_imports,
    is_min_build,
)

_FEATURE_COLLECT_SUBMODULES = (
    "browser_window",
    "slideshow",
    "theme",
    "exif",
    "search",
    "cache",
    "faces",
    "workers",
    "files",
    "thumbnails",
    "settings",
)

_WINDOWS_EXCLUDES = (
    "win32com",
    "win32api",
    "win32con",
    "win32gui",
    "win32print",
    "win32process",
    "win32security",
    "win32service",
    "win32serviceutil",
    "win32timezone",
    "win32traceutil",
    "win32ui",
    "win32wnet",
    "pywintypes",
    "pythoncom",
    "winreg",
    "msilib",
    "msvcrt",
)


def _script_dir() -> str:
    return os.environ.get("SCRIPT_DIR", os.getcwd())


def _load_analyzer_directives() -> dict:
    path = os.path.join(_script_dir(), "pyinstaller_directives.json")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _load_local_hidden() -> tuple[list[str], list[str]]:
    import json as _json

    local_json = _json.loads(os.environ.get("LOCAL_PACKAGES_HIDDEN_JSON", "[]") or "[]")
    imagegen_json = _json.loads(os.environ.get("IMAGEGEN_HIDDEN_JSON", "[]") or "[]")
    if not imagegen_json:
        imagegen_json = ["imagegen_plugins"]
    if not local_json:
        local_json = list(imagegen_json)
    return local_json, imagegen_json


def merged_directives() -> tuple[list[str], list[str], list[str]]:
    data = _load_analyzer_directives()
    hidden = set(filter_hidden_imports(data.get("hidden_imports", [])))
    collect_all = set(data.get("collect_all", []))
    excludes = set(data.get("excludes", []))

    hidden.update(MANDATORY_PYOBJC_HIDDEN)
    hidden.update(MANDATORY_HIDDEN)

    local_hidden, imagegen_hidden = _load_local_hidden()
    hidden.update(local_hidden)
    hidden.update(imagegen_hidden)

    if is_min_build():
        hidden.update(MIN_BUILD_EXTRA_HIDDEN)
        collect_all.update(MIN_BUILD_COLLECT_ALL)
        excludes.update(MIN_EXCLUDE_MODULES)
    else:
        hidden.update(FULL_BUILD_EXTRA_HIDDEN)
        collect_all.update(FULL_BUILD_COLLECT_ALL)

    hidden = set(filter_hidden_imports(hidden))
    excludes.update(_WINDOWS_EXCLUDES)
    excludes.update(ALWAYS_EXCLUDE_IMPORT_ROOTS)
    excludes.update({"skimage", "imagehash"})

    return sorted(hidden), sorted(collect_all), sorted(excludes)


def collect_submodules_cli() -> str:
    parts = [f"--collect-submodules {pkg}" for pkg in _FEATURE_COLLECT_SUBMODULES]
    extra = (
        MIN_EXTRA_COLLECT_SUBMODULES
        if is_min_build()
        else FULL_EXTRA_COLLECT_SUBMODULES
    )
    parts.extend(f"--collect-submodules {pkg}" for pkg in extra)
    return " ".join(parts)


def spec_collect_packages() -> tuple[str, ...]:
    return MIN_SPEC_COLLECT_PACKAGES if is_min_build() else FULL_SPEC_COLLECT_PACKAGES


def spec_copy_metadata_packages() -> tuple[str, ...]:
    return MIN_SPEC_COPY_METADATA if is_min_build() else FULL_SPEC_COPY_METADATA


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: pyinstaller_build_directives.py <command>", file=sys.stderr)
        sys.exit(1)

    cmd = sys.argv[1]
    if cmd == "shell":
        hidden, collect_all, excludes = merged_directives()
        print(f"HIDDEN_IMPORTS={' '.join(hidden) if hidden else ''}")
        print(f"COLLECT_ALL={' '.join(collect_all) if collect_all else ''}")
        print(f"EXCLUDES={' '.join(excludes) if excludes else ''}")
    elif cmd == "repr":
        hidden, collect_all, excludes = merged_directives()
        print(f"HIDDEN_IMPORTS={hidden!r}")
        print(f"COLLECT_ALL={collect_all!r}")
        print(f"EXCLUDES={excludes!r}")
    elif cmd == "collect-submodules-cli":
        print(collect_submodules_cli())
    elif cmd == "spec-collect-packages":
        print(repr(list(spec_collect_packages())))
    elif cmd == "spec-copy-metadata":
        print(repr(list(spec_copy_metadata_packages())))
    elif cmd == "is-min":
        print("1" if is_min_build() else "0")
    else:
        print(f"Unknown command: {cmd}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
