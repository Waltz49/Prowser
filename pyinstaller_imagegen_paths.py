#!/usr/bin/env python3
"""Emit PyInstaller pathex / hookspath / imagegen hiddenimports for pyInstallerBuild.sh."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def _imagegen_hidden_imports(root: str) -> list[str]:
    if root not in sys.path:
        sys.path.insert(0, root)
    try:
        from PyInstaller.utils.hooks import collect_submodules

        return sorted(set(collect_submodules("imagegen_plugins")))
    except Exception:
        pkg = Path(root) / "imagegen_plugins"
        if not pkg.is_dir():
            return []
        names = ["imagegen_plugins"]
        for py in sorted(pkg.rglob("*.py")):
            rel = py.relative_to(pkg)
            if rel.name == "__init__.py":
                if rel.parent != Path("."):
                    names.append("imagegen_plugins." + ".".join(rel.parent.parts))
                continue
            mod = "imagegen_plugins." + ".".join(rel.with_suffix("").parts)
            names.append(mod)
        return sorted(set(names))


def main() -> None:
    root = os.path.abspath(os.environ.get("SCRIPT_DIR", os.getcwd()))
    hooks = str(Path(root) / "pyinstaller_hooks")
    print(f"PATHEX={json.dumps([root])}")
    print(f"HOOKSPATH={json.dumps([hooks])}")
    print(f"IMAGEGEN_HIDDEN={json.dumps(_imagegen_hidden_imports(root))}")


if __name__ == "__main__":
    main()
