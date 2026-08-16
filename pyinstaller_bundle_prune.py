#!/usr/bin/env python3
"""Drop confirmed-unused files from a PyInstaller Analysis TOC.

Called from the generated Prowser.spec after Analysis(). Exclusions here are
things PyInstaller still collects via Qt plugins, collect_all, or optional
imports even when --exclude-module is set.
"""

from __future__ import annotations


# dest-name prefixes (POSIX, case-sensitive as collected on macOS).
_DROP_PREFIXES: tuple[str, ...] = (
    "cv2/",
    "cv2.",
    "matplotlib/",
    "mpl_toolkits/",
    "mpl-data/",
    "contourpy/",
    "kiwisolver/",
    "cycler/",
    "IPython/",
    "jupyter/",
    "notebook/",
    "pytest/",
    "_pytest/",
    "pandas/",
    "scipy/",
    "twine/",
    "torch/testing/",
    "torch/bin/protoc",
)

_DROP_ROOTS: frozenset[str] = frozenset(
    {
        "cv2",
        "matplotlib",
        "mpl_toolkits",
        "contourpy",
        "kiwisolver",
        "cycler",
        "QtPdf",
        "QtQml",
        "QtQmlMeta",
        "QtQmlModels",
        "QtQmlWorkerScript",
        "QtQuick",
        "QtVirtualKeyboard",
        "QtVirtualKeyboardQml",
    }
)

# Native Qt payloads pulled in by the PDF imageformat plugin and the
# virtual-keyboard platforminputcontexts plugin (neither is used).
_DROP_SUBSTRINGS: tuple[str, ...] = (
    "libqpdf",
    "qtvirtualkeyboard",
    "QtPdf.framework",
    "QtQuick.framework",
    "QtQml.framework",
    "QtQmlMeta.framework",
    "QtQmlModels.framework",
    "QtQmlWorkerScript.framework",
    "QtVirtualKeyboard.framework",
    "QtVirtualKeyboardQml.framework",
)


def _dest(entry: object) -> str:
    if isinstance(entry, (tuple, list)) and entry:
        return str(entry[0]).replace("\\", "/")
    return str(entry).replace("\\", "/")


def _src(entry: object) -> str:
    if isinstance(entry, (tuple, list)) and len(entry) > 1:
        return str(entry[1]).replace("\\", "/")
    return ""


def _should_drop(entry: object) -> bool:
    dest = _dest(entry)
    src = _src(entry)
    combined = dest if dest else src
    if not combined:
        return False
    root = combined.split("/", 1)[0]
    dotted_root = combined.replace("/", ".").split(".", 1)[0]
    if root in _DROP_ROOTS or dotted_root in _DROP_ROOTS:
        return True
    if dest.endswith(".pyi") or src.endswith(".pyi"):
        return True
    lowered = combined.lower()
    if "/tests/" in lowered or lowered.endswith("/tests"):
        return True
    for prefix in _DROP_PREFIXES:
        if dest.startswith(prefix) or src.startswith(prefix):
            return True
    for needle in _DROP_SUBSTRINGS:
        if needle in dest or needle in src:
            return True
    return False


def _filter_toc(toc: object) -> tuple[object, int]:
    entries = list(toc)
    kept = [entry for entry in entries if not _should_drop(entry)]
    dropped = len(entries) - len(kept)
    try:
        return type(toc)(kept), dropped
    except TypeError:
        return kept, dropped


def prune_analysis(analysis: object) -> None:
    """Filter Analysis.binaries / .datas / .pure in place; print a short summary."""
    total_dropped = 0
    for attr in ("binaries", "datas", "pure"):
        toc = getattr(analysis, attr, None)
        if toc is None:
            continue
        filtered, dropped = _filter_toc(toc)
        setattr(analysis, attr, filtered)
        total_dropped += dropped
    if total_dropped:
        print(f"pyinstaller_bundle_prune: dropped {total_dropped} unused TOC entries")
    else:
        print("pyinstaller_bundle_prune: no extra TOC entries dropped")
