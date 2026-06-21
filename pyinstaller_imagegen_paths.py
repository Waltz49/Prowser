#!/usr/bin/env python3
"""Emit PyInstaller pathex / hookspath / imagegen hiddenimports for pyInstallerBuild.sh."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path


LOCAL_PACKAGES = (
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
)


def _fallback_package_modules(root: str, package: str) -> list[str]:
    pkg = Path(root) / package
    if not pkg.is_dir():
        return []
    names = [package]
    for py in sorted(pkg.rglob("*.py")):
        rel = py.relative_to(pkg)
        if rel.name == "__init__.py":
            if rel.parent != Path("."):
                names.append(package + "." + ".".join(rel.parent.parts))
            continue
        mod = package + "." + ".".join(rel.with_suffix("").parts)
        names.append(mod)
    return sorted(set(names))


def _package_hidden_imports(root: str, package: str) -> list[str]:
    if root not in sys.path:
        sys.path.insert(0, root)
    try:
        from PyInstaller.utils.hooks import collect_submodules

        return sorted(set(collect_submodules(package)))
    except Exception:
        return _fallback_package_modules(root, package)


def _local_packages_hidden_imports(root: str) -> list[str]:
    names: set[str] = set()
    for package in LOCAL_PACKAGES:
        names.update(_package_hidden_imports(root, package))
    return sorted(names)


def main() -> None:
    root = os.path.abspath(os.environ.get("SCRIPT_DIR", os.getcwd()))
    hooks = str(Path(root) / "pyinstaller_hooks")
    local_hidden = _local_packages_hidden_imports(root)
    imagegen_hidden = [n for n in local_hidden if n == "imagegen_plugins" or n.startswith("imagegen_plugins.")]
    print(f"PATHEX={json.dumps([root])}")
    print(f"HOOKSPATH={json.dumps([hooks])}")
    print(f"IMAGEGEN_HIDDEN={json.dumps(imagegen_hidden)}")
    print(f"LOCAL_PACKAGES_HIDDEN={json.dumps(local_hidden)}")


if __name__ == "__main__":
    main()
