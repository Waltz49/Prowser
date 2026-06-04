#!/usr/bin/env python3
"""List asset files referenced by application code (for copy/build scripts)."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent
_ASSETS_DIR = _REPO_ROOT / "assets"
_SKIP_DIR_PARTS = {
    "venv_image_browser",
    "venv",
    "__pycache__",
    ".pyinstaller_face_models",
    "build",
    "dist",
}

_SCAN_RE = re.compile(
    r"""
    asset_(?:path|file_url|url)\(\s*['"]([^'"]+)['"]\)
    | au\(\s*['"]([^'"]+)['"]\)
    | _asset_url\(\s*['"]([^'"]+)['"]\)
    | ['"]assets/([^'"]+\.(?:png|svg|webp))['"]
    | ,\s*['"]assets['"],\s*['"]([^'"]+)['"]\)
    """,
    re.VERBOSE,
)

# Constants not always visible to the scanner.
_EXTRA_NAMES = frozenset({"expansion_template.webp"})


def _iter_py_files() -> list[Path]:
    files: list[Path] = []
    for path in _REPO_ROOT.rglob("*.py"):
        if any(part in _SKIP_DIR_PARTS for part in path.parts):
            continue
        files.append(path)
    return files


def collect_runtime_asset_names() -> list[str]:
    names: set[str] = set(_EXTRA_NAMES)
    for path in _iter_py_files():
        if path.name == "list_runtime_assets.py":
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for match in _SCAN_RE.finditer(text):
            name = next(g for g in match.groups() if g)
            names.add(name)
        if path.name == "image_gen_job_queue_dialog.py":
            for m in re.finditer(r'["\']([a-z0-9_]+\.(?:png|svg|webp))["\']', text):
                n = m.group(1)
                if any(k in n for k in ("icon", "series", "trash", "edit")):
                    names.add(n)

    # _icon_push_button_stylesheet uses <stem>_hover.png for .png icons.
    expanded = set(names)
    for name in list(names):
        if name.endswith(".png") and not name.endswith("_hover.png"):
            hover = name.replace(".png", "_hover.png")
            if (_ASSETS_DIR / hover).is_file():
                expanded.add(hover)

    missing = sorted(n for n in expanded if not (_ASSETS_DIR / n).is_file())
    if missing:
        print(f"Warning: referenced assets missing from {_ASSETS_DIR}:", ", ".join(missing), file=sys.stderr)

    return sorted(n for n in expanded if (_ASSETS_DIR / n).is_file())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--format",
        choices=("paths", "pyinstaller"),
        default="paths",
        help="paths: assets/<name> per line; pyinstaller: Analysis datas tuples",
    )
    args = parser.parse_args()
    names = collect_runtime_asset_names()
    if args.format == "paths":
        for name in names:
            print(f"assets/{name}")
    else:
        for name in names:
            print(f"        ('assets/{name}', 'assets'),")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
