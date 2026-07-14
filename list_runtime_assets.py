#!/usr/bin/env python3
"""List asset files referenced by application code (for copy/build scripts)."""

from __future__ import annotations

import argparse
import ast
import re
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent
_ASSETS_DIR = _REPO_ROOT / "assets"
_SKIP_DIR_PARTS = {
    "venv_image_browser",
    "venv_pyinstaller",
    "venv",
    "__pycache__",
    ".pyinstaller_face_models",
    "build",
    "dist",
    "tests",
    "tools",
    "scripts",
}

# Keep in sync with FEATURE_PACKAGES in copy_project_files.sh (runtime app packages).
_APP_PACKAGES = frozenset(
    {
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
        "imagegen_plugins",
        "chat_plugins",
    }
)

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

# asset_file_url(variable) and similar — literal filename must match a file in assets/.
_LITERAL_ASSET_RE = re.compile(r"""['"]([a-zA-Z0-9_]+\.(?:png|svg|webp))['"]""")

# Constants not always visible to the scanner.
_EXTRA_NAMES = frozenset({"expansion_template.webp"})


def _imports_in(path: Path) -> list[str]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
    except (OSError, SyntaxError, ValueError):
        return []
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                modules.append(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.append(node.module)
    return modules


def _module_to_path(module: str) -> Path | None:
    parts = module.split(".")
    top = parts[0]
    if top in _APP_PACKAGES or (_REPO_ROOT / f"{top}.py").is_file():
        path = _REPO_ROOT.joinpath(*parts)
        py_path = path.with_suffix(".py")
        if py_path.is_file():
            return py_path
        init = path / "__init__.py"
        if init.is_file():
            return init
        if len(parts) == 1:
            pkg_init = _REPO_ROOT / top / "__init__.py"
            if pkg_init.is_file():
                return pkg_init
    if len(parts) == 1:
        root_py = _REPO_ROOT / f"{top}.py"
        if root_py.is_file():
            return root_py
    return None


def _reachable_py_files_from_main() -> list[Path]:
    """Python modules imported (transitively) from main.py."""
    seen: set[Path] = set()
    stack = [_REPO_ROOT / "main.py"]
    while stack:
        path = stack.pop()
        if path in seen or not path.is_file():
            continue
        if any(part in _SKIP_DIR_PARTS for part in path.parts):
            continue
        seen.add(path)
        for module in _imports_in(path):
            target = _module_to_path(module)
            if target is not None and target not in seen:
                stack.append(target)
    return sorted(seen)


def _iter_py_files() -> list[Path]:
    files: list[Path] = []
    for path in _REPO_ROOT.rglob("*.py"):
        if any(part in _SKIP_DIR_PARTS for part in path.parts):
            continue
        files.append(path)
    return files


def _asset_names_from_py_files(py_files: list[Path]) -> list[str]:
    names: set[str] = set(_EXTRA_NAMES)
    for path in py_files:
        if path.name == "list_runtime_assets.py":
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for match in _SCAN_RE.finditer(text):
            name = next(g for g in match.groups() if g)
            names.add(name)
        for match in _LITERAL_ASSET_RE.finditer(text):
            name = match.group(1)
            if (_ASSETS_DIR / name).is_file():
                names.add(name)

    # _icon_push_button_stylesheet uses <stem>_hover.png for .png icons.
    expanded = set(names)
    for name in list(names):
        if name.endswith(".png") and not name.endswith("_hover.png"):
            hover = name.replace(".png", "_hover.png")
            if (_ASSETS_DIR / hover).is_file():
                expanded.add(hover)

    missing = sorted(n for n in expanded if not (_ASSETS_DIR / n).is_file())
    if missing:
        print(
            f"Warning: referenced assets missing from {_ASSETS_DIR}:",
            ", ".join(missing),
            file=sys.stderr,
        )

    return sorted(n for n in expanded if (_ASSETS_DIR / n).is_file())


def collect_runtime_asset_names(*, from_main: bool = False) -> list[str]:
    py_files = _reachable_py_files_from_main() if from_main else _iter_py_files()
    return _asset_names_from_py_files(py_files)


def reachable_root_py_filenames() -> list[str]:
    """Root-level .py modules imported (transitively) from main.py."""
    return sorted(
        p.name
        for p in _reachable_py_files_from_main()
        if p.parent == _REPO_ROOT and p.suffix == ".py"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--from-main",
        action="store_true",
        help="Only scan Python reachable from main.py (omit dev-only modules).",
    )
    parser.add_argument(
        "--reachable-root-py",
        action="store_true",
        help="Print root-level .py filenames reachable from main.py (one per line).",
    )
    parser.add_argument(
        "--format",
        choices=("paths", "pyinstaller"),
        default="paths",
        help="paths: assets/<name> per line; pyinstaller: Analysis datas tuples",
    )
    args = parser.parse_args()
    if args.reachable_root_py:
        for name in reachable_root_py_filenames():
            print(name)
        return 0
    names = collect_runtime_asset_names(from_main=args.from_main)
    if args.format == "paths":
        for name in names:
            print(f"assets/{name}")
    else:
        for name in names:
            print(f"        ('assets/{name}', 'assets'),")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
