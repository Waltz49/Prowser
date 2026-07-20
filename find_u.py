#!/usr/bin/env python3
"""
Find unused functions and methods in the Prowser (prowser.py) project.

Uses AST indexing + import-graph reachability from known entry points.
Conservative by design: ambiguous references mark every same-named definition
in reachable modules as used; Qt/plugin hooks are whitelisted explicitly.

Update DYNAMIC_METHOD_NAMES / ENTRY_MODULES when adding new subprocess workers,
pipeline entry points, or framework callbacks that are not called by name in code.
"""

from __future__ import annotations

import argparse
import ast
import sys
import time
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import DefaultDict, Dict, Iterable, Iterator, List, Optional, Set, Tuple

SCRIPT_VERSION = "1.0.0"

# Repo root = directory containing this script (and prowser.py).
PROJECT_ROOT = Path(__file__).resolve().parent

# Modules treated as application entry points (import closure starts here).
ENTRY_MODULES: Tuple[str, ...] = (
    "prowser",
    "workers.model_tasks_worker",
    "workers.background_clip_worker",
    "imagegen_plugins.image_gen_worker_entry",
    # Pipeline subprocess targets (imported dynamically from image_gen_worker_entry).
    "imagegen_plugins.pipelines.mflux_schnell",
    "imagegen_plugins.pipelines.sana_sprint",
    "imagegen_plugins.pipelines.sd15_diffusers",
    "imagegen_plugins.pipelines.mflux_fill_expand",
    "imagegen_plugins.pipelines.mflux_flux2_klein_create",
    "imagegen_plugins.pipelines.mflux_flux2_klein_edit",
    "imagegen_plugins.pipelines.z_image_turbo",
)

# Extra qualified names seeded as used even if static analysis misses them.
ENTRY_QUALNAMES: Tuple[str, ...] = (
    "prowser.main",
    "workers.model_tasks_worker.main",
    "workers.model_tasks_worker.run_worker_event_loop",
    "workers.background_clip_worker.main",
    "imagegen_plugins.image_gen_worker_entry.run_worker_main",
)

SKIP_DIR_NAMES: frozenset[str] = frozenset(
    {
        "__pycache__",
        ".git",
        ".cache",
        "build",
        "dist",
        "venv",
        "venv_image_browser",
        "venv_pyinstaller",
        ".pytest_cache",
        "source_preblessed",
    }
)

# Base-class name fragments that mark a Qt / framework subclass.
QT_BASE_MARKERS: frozenset[str] = frozenset(
    {
        "QObject",
        "QWidget",
        "QFrame",
        "QDialog",
        "QMainWindow",
        "QApplication",
        "QAbstractItemModel",
        "QAbstractListModel",
        "QAbstractTableModel",
        "QSortFilterProxyModel",
        "QStyledItemDelegate",
        "QAbstractItemDelegate",
        "QItemDelegate",
        "QTreeView",
        "QListView",
        "QTableView",
        "QGraphicsView",
        "QGraphicsItem",
        "QThread",
        "QRunnable",
        "QProxyStyle",
        "QStyle",
        "QCompleter",
        "QLineEdit",
        "QPlainTextEdit",
        "QTextEdit",
        "QScrollArea",
        "QTabWidget",
        "QToolBar",
        "QMenu",
        "QAction",
        "QTimer",
        "QEvent",
        "ABC",
        "Protocol",
    }
)

# Methods invoked by Qt, plugins, or other runtime machinery without a static call.
# Add new names here when introducing similar dynamic hooks.
DYNAMIC_METHOD_NAMES: frozenset[str] = frozenset(
    {
        # Qt widget / model virtuals
        "paintEvent",
        "resizeEvent",
        "moveEvent",
        "showEvent",
        "hideEvent",
        "closeEvent",
        "keyPressEvent",
        "keyReleaseEvent",
        "mousePressEvent",
        "mouseReleaseEvent",
        "mouseMoveEvent",
        "mouseDoubleClickEvent",
        "wheelEvent",
        "enterEvent",
        "leaveEvent",
        "focusInEvent",
        "focusOutEvent",
        "changeEvent",
        "event",
        "eventFilter",
        "paint",
        "drawRow",
        "drawBranches",
        "sizeHint",
        "minimumSizeHint",
        "createEditor",
        "setEditorData",
        "setModelData",
        "updateEditorGeometry",
        "initStyleOption",
        "data",
        "setData",
        "headerData",
        "flags",
        "index",
        "parent",
        "rowCount",
        "columnCount",
        "hasChildren",
        "sort",
        "lessThan",
        "filterAcceptsRow",
        "filterAcceptsColumn",
        "canDropMimeData",
        "dropMimeData",
        "mimeTypes",
        "supportedDropActions",
        "run",
        "execute",
        # Image-gen plugin / pipeline API
        "is_available",
        "build_payload",
        "field_specs",
        "merged_values",
        "worker_script",
        "model_label",
        "menu_label",
        "persist_reproducible_seed",
        "quantize_status_value",
        "pipeline_reports_quantization",
        # Common dialog / controller lifecycle
        "accept",
        "reject",
        "done",
        "exec",
        "exec_",
        "show",
        "close",
        "setupUi",
    }
)

SLOT_DECORATORS: frozenset[str] = frozenset({"Slot", "pyqtSlot", "PySide6.QtCore.Slot"})
ABSTRACT_DECORATORS: frozenset[str] = frozenset({"abstractmethod", "abc.abstractmethod"})


@dataclass(frozen=True)
class FuncDef:
    module: str
    qualname: str
    name: str
    path: Path
    lineno: int
    is_method: bool
    is_nested: bool
    is_magic: bool
    is_property: bool
    in_qt_class: bool
    has_slot: bool
    has_abstract: bool

    @property
    def key(self) -> Tuple[str, str]:
        return (self.module, self.qualname)


def _decorator_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Call):
        return _decorator_name(node.func)
    return ""


def _is_qt_class(bases: List[ast.expr]) -> bool:
    for base in bases:
        if isinstance(base, ast.Name) and (
            base.id in QT_BASE_MARKERS or base.id.startswith("Q")
        ):
            return True
        if isinstance(base, ast.Attribute) and (
            base.attr in QT_BASE_MARKERS or base.attr.startswith("Q")
        ):
            return True
        if isinstance(base, ast.Name) and base.id in {"ABC", "Protocol"}:
            return True
    return False


class DefinitionIndexer(ast.NodeVisitor):
    def __init__(self, module: str, path: Path) -> None:
        self.module = module
        self.path = path
        self.defs: List[FuncDef] = []
        self.classes: Dict[str, bool] = {}
        self._class_stack: List[str] = []
        self._function_stack: List[str] = []

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        qt = _is_qt_class(node.bases)
        self.classes[node.name] = qt
        self._class_stack.append(node.name)
        self.generic_visit(node)
        self._class_stack.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._record_function(node, is_async=False)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._record_function(node, is_async=True)

    def _record_function(self, node: ast.AST, is_async: bool) -> None:
        name = node.name  # type: ignore[attr-defined]
        lineno = node.lineno  # type: ignore[attr-defined]
        decorators = getattr(node, "decorator_list", [])
        deco_names = {_decorator_name(d) for d in decorators}
        is_property = "property" in deco_names or any(
            _decorator_name(d) == "setter" for d in decorators
        )
        has_slot = bool(deco_names & SLOT_DECORATORS) or any(
            n.endswith("Slot") for n in deco_names
        )
        has_abstract = bool(deco_names & ABSTRACT_DECORATORS)
        is_nested = len(self._function_stack) > 0
        class_name = self._class_stack[-1] if self._class_stack else None
        is_method = class_name is not None
        qualname = f"{class_name}.{name}" if is_method else name
        in_qt = bool(class_name and self.classes.get(class_name, False))
        self.defs.append(
            FuncDef(
                module=self.module,
                qualname=qualname,
                name=name,
                path=self.path,
                lineno=lineno,
                is_method=is_method,
                is_nested=is_nested,
                is_magic=name.startswith("__") and name.endswith("__"),
                is_property=is_property,
                in_qt_class=in_qt,
                has_slot=has_slot,
                has_abstract=has_abstract,
            )
        )
        self._function_stack.append(name)
        self.generic_visit(node)
        self._function_stack.pop()


@dataclass
class ImportBinding:
    module: str
    name: Optional[str]  # None => import module itself


@dataclass
class ModuleInfo:
    module: str
    path: Path
    tree: ast.AST
    defs: List[FuncDef]
    imports: Dict[str, ImportBinding]
    classes: Dict[str, bool]


class ProjectIndex:
    def __init__(self, root: Path, include_tests: bool = False) -> None:
        self.root = root
        self.include_tests = include_tests
        self.path_by_module: Dict[str, Path] = {}
        self.module_by_path: Dict[Path, str] = {}
        self.modules: Dict[str, ModuleInfo] = {}
        self.def_by_key: Dict[Tuple[str, str], FuncDef] = {}
        self.defs_by_name: DefaultDict[str, List[FuncDef]] = defaultdict(list)
        self._parse_all()

    def _iter_py_files(self) -> Iterator[Path]:
        for path in sorted(self.root.rglob("*.py")):
            if any(part in SKIP_DIR_NAMES for part in path.parts):
                continue
            if not self.include_tests and "tests" in path.parts:
                continue
            yield path

    def _path_to_module(self, path: Path) -> Optional[str]:
        try:
            rel = path.relative_to(self.root)
        except ValueError:
            return None
        if rel.name == "__init__.py":
            parts = rel.parts[:-1]
        else:
            parts = rel.with_suffix("").parts
        if not parts:
            return None
        return ".".join(parts)

    def _module_to_path(self, module: str) -> Optional[Path]:
        parts = module.split(".")
        py_file = self.root.joinpath(*parts).with_suffix(".py")
        if py_file.is_file():
            return py_file
        init_file = self.root.joinpath(*parts, "__init__.py")
        if init_file.is_file():
            return init_file
        return None

    def _parse_all(self) -> None:
        for path in self._iter_py_files():
            module = self._path_to_module(path)
            if not module:
                continue
            try:
                source = path.read_text(encoding="utf-8")
                tree = ast.parse(source, filename=str(path))
            except (OSError, SyntaxError) as exc:
                print(f"Warning: skip {path}: {exc}", file=sys.stderr)
                continue
            indexer = DefinitionIndexer(module, path)
            indexer.visit(tree)
            imports = self._extract_imports(tree, module)
            info = ModuleInfo(
                module=module,
                path=path,
                tree=tree,
                defs=indexer.defs,
                imports=imports,
                classes=indexer.classes,
            )
            self.path_by_module[module] = path
            self.module_by_path[path.resolve()] = module
            self.modules[module] = info
            for d in indexer.defs:
                self.def_by_key[d.key] = d
                self.defs_by_name[d.name].append(d)

    def _extract_imports(self, tree: ast.AST, module: str) -> Dict[str, ImportBinding]:
        bindings: Dict[str, ImportBinding] = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    local = alias.asname or alias.name.split(".")[0]
                    bindings[local] = ImportBinding(module=alias.name, name=None)
            elif isinstance(node, ast.ImportFrom):
                base = self._resolve_import_from(module, node.level, node.module)
                if base is None:
                    continue
                for alias in node.names:
                    if alias.name == "*":
                        continue
                    local = alias.asname or alias.name
                    bindings[local] = ImportBinding(module=base, name=alias.name)
        return bindings

    @staticmethod
    def _resolve_import_from(
        from_module: str, level: int, module: Optional[str]
    ) -> Optional[str]:
        parts = from_module.split(".")
        if level:
            if level > len(parts):
                anchor: List[str] = []
            else:
                anchor = parts[: len(parts) - level]
        else:
            anchor = []
        if module:
            anchor.extend(module.split("."))
        if not anchor:
            return None
        return ".".join(anchor)

    def resolve_module(self, from_module: str, binding: ImportBinding) -> str:
        if binding.name is None:
            return binding.module
        return binding.module

    def reachable_modules(self, entries: Iterable[str]) -> Set[str]:
        seen: Set[str] = set()
        queue = [m for m in entries if m in self.modules]
        while queue:
            mod = queue.pop()
            if mod in seen:
                continue
            seen.add(mod)
            info = self.modules.get(mod)
            if not info:
                continue
            for binding in info.imports.values():
                target = binding.module if binding.name is None else binding.module
                if target in self.modules and target not in seen:
                    queue.append(target)
                if binding.name is not None:
                    sub = f"{binding.module}.{binding.name}"
                    if sub in self.modules:
                        if sub not in seen:
                            queue.append(sub)
        return seen


class ReferenceScanner(ast.NodeVisitor):
    """Collect resolved definition keys and ambiguous simple names."""

    def __init__(self, index: ProjectIndex, module: str) -> None:
        self.index = index
        self.module = module
        self.info = index.modules[module]
        self.used_keys: Set[Tuple[str, str]] = set()
        self.dynamic_names: Set[str] = set()
        self._class_stack: List[str] = []
        self._local_classes: Set[str] = set(self.info.classes)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._class_stack.append(node.name)
        self._local_classes.add(node.name)
        self.generic_visit(node)
        self._class_stack.pop()

    def visit_Call(self, node: ast.Call) -> None:
        if (
            isinstance(node.func, ast.Name)
            and node.func.id == "getattr"
            and len(node.args) >= 2
            and isinstance(node.args[1], ast.Constant)
            and isinstance(node.args[1].value, str)
        ):
            self.dynamic_names.add(node.args[1].value)
        self._visit_callable(node.func)
        if self._is_connect_call(node) and node.args:
            self._visit_connect_target(node.args[0])
        self.generic_visit(node)

    def _is_connect_call(self, node: ast.Call) -> bool:
        func = node.func
        return isinstance(func, ast.Attribute) and func.attr == "connect"

    def _visit_connect_target(self, node: ast.AST) -> None:
        if isinstance(node, ast.Name):
            self._resolve_name(node.id, call=True)
        elif isinstance(node, ast.Attribute):
            self._visit_attribute(node, call=True)
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr in {"partial", "method"}:
                if node.args:
                    self._visit_connect_target(node.args[0])

    def _visit_callable(self, node: ast.AST) -> None:
        if isinstance(node, ast.Name):
            self._resolve_name(node.id, call=True)
        elif isinstance(node, ast.Attribute):
            self._visit_attribute(node, call=True)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if not isinstance(node.ctx, ast.Load):
            self.generic_visit(node)
            return
        parent = node.value
        if isinstance(parent, ast.Call):
            return
        if isinstance(parent, ast.Name) and parent.id == "super":
            self._mark_current_class_method(node.attr)
            return
        self._visit_attribute(node, call=False)
        self.generic_visit(node)

    def visit_Assign(self, node: ast.Assign) -> None:
        if isinstance(node.value, ast.Attribute):
            self._visit_attribute(node.value, call=False)
        self.generic_visit(node)

    def visit_Constant(self, node: ast.Constant) -> None:
        if isinstance(node.value, str) and node.value.isidentifier():
            self.dynamic_names.add(node.value)

    def _visit_attribute(self, node: ast.Attribute, call: bool) -> None:
        name = node.attr
        value = node.value
        if isinstance(value, ast.Name):
            if value.id == "self" and self._class_stack:
                self._mark_method(self._class_stack[-1], name)
                return
            if value.id == "cls" and self._class_stack:
                self._mark_method(self._class_stack[-1], name)
                return
            if value.id == "super" and self._class_stack:
                self._mark_current_class_method(name)
                return
            binding = self.info.imports.get(value.id)
            if binding:
                if binding.name is None:
                    self._mark_module_attr(binding.module, name)
                else:
                    method_key = (binding.module, f"{binding.name}.{name}")
                    if method_key in self.index.def_by_key:
                        self.used_keys.add(method_key)
                    else:
                        self._mark_module_attr(binding.module, binding.name)
                return
            if value.id in self._local_classes:
                self._mark_method(value.id, name)
                return
            if value.id in self.info.classes:
                self._mark_method(value.id, name)
                return
        self.dynamic_names.add(name)

    def _resolve_name(self, name: str, call: bool) -> None:
        binding = self.info.imports.get(name)
        if binding:
            if binding.name is None:
                return
            self._mark_module_attr(binding.module, binding.name)
            return
        key = (self.module, name)
        if key in self.index.def_by_key:
            self.used_keys.add(key)

    def _mark_method(self, class_name: str, method_name: str) -> None:
        key = (self.module, f"{class_name}.{method_name}")
        if key in self.index.def_by_key:
            self.used_keys.add(key)

    def _mark_current_class_method(self, method_name: str) -> None:
        if self._class_stack:
            self._mark_method(self._class_stack[-1], method_name)

    def _mark_module_attr(self, module: str, attr: str) -> None:
        key = (module, attr)
        if key in self.index.def_by_key:
            self.used_keys.add(key)


def _seed_dynamic(defs: Iterable[FuncDef]) -> Set[Tuple[str, str]]:
    used: Set[Tuple[str, str]] = set()
    for d in defs:
        if d.is_nested or d.is_magic:
            continue
        if d.has_slot or d.has_abstract:
            used.add(d.key)
            continue
        if d.in_qt_class and (
            d.name in DYNAMIC_METHOD_NAMES
            or d.name.endswith("Event")
            or d.name.endswith("Changed")
        ):
            used.add(d.key)
            continue
        if d.name in DYNAMIC_METHOD_NAMES:
            used.add(d.key)
    return used


def _seed_entry_qualnames(index: ProjectIndex) -> Set[Tuple[str, str]]:
    used: Set[Tuple[str, str]] = set()
    for qual in ENTRY_QUALNAMES:
        module, _, name = qual.rpartition(".")
        key = (module, name)
        if key in index.def_by_key:
            used.add(key)
    for module in ENTRY_MODULES:
        for candidate in ("main", "run_worker_main", "run_worker_event_loop"):
            key = (module, candidate)
            if key in index.def_by_key:
                used.add(key)
    return used


def analyze(
    index: ProjectIndex,
    *,
    file_filter: Optional[Path] = None,
) -> Tuple[List[FuncDef], Set[str]]:
    reachable = index.reachable_modules(ENTRY_MODULES)
    scanners: List[ReferenceScanner] = []
    dynamic_names: Set[str] = set()

    for module in sorted(reachable):
        scanner = ReferenceScanner(index, module)
        scanner.visit(index.modules[module].tree)
        scanners.append(scanner)
        dynamic_names.update(scanner.dynamic_names)

    used = _seed_dynamic(index.def_by_key.values())
    used |= _seed_entry_qualnames(index)
    for scanner in scanners:
        used.update(scanner.used_keys)

    for name in dynamic_names:
        for d in index.defs_by_name.get(name, []):
            if d.module in reachable:
                used.add(d.key)

    reportable = []
    for d in index.def_by_key.values():
        if d.module not in reachable:
            continue
        if file_filter is not None and d.path.resolve() != file_filter.resolve():
            continue
        if d.is_nested or d.is_magic or d.is_property:
            continue
        if d.key not in used:
            reportable.append(d)

    reportable.sort(key=lambda d: (str(d.path), d.lineno, d.qualname))
    return reportable, reachable


def _format_def(d: FuncDef) -> str:
    kind = "method" if d.is_method else "function"
    return f"{d.path}:{d.lineno}: {d.qualname} ({kind})"


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Find unused functions/methods in the Prowser project."
    )
    parser.add_argument(
        "file",
        nargs="?",
        help="Optional file path to restrict results (e.g. settings_dialog.py)",
    )
    parser.add_argument(
        "--include-tests",
        action="store_true",
        help="Include tests/ in module index (still not entry points)",
    )
    parser.add_argument(
        "--list-reachable",
        action="store_true",
        help="Print reachable modules and exit",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"find_u.py {SCRIPT_VERSION}",
    )
    args = parser.parse_args(argv)

    start = time.time()
    index = ProjectIndex(PROJECT_ROOT, include_tests=args.include_tests)
    file_filter: Optional[Path] = None
    if args.file:
        file_filter = Path(args.file)
        if not file_filter.is_absolute():
            file_filter = (PROJECT_ROOT / file_filter).resolve()
        if not file_filter.is_file():
            print(f"Error: file not found: {file_filter}", file=sys.stderr)
            return 1

    unused, reachable = analyze(index, file_filter=file_filter)

    if args.list_reachable:
        for mod in sorted(reachable):
            path = index.path_by_module.get(mod)
            print(f"{mod}\t{path}")
        return 0

    if not unused:
        scope = file_filter or PROJECT_ROOT / "prowser.py"
        print(f"No unused functions/methods found (scope: {scope})")
    else:
        current_path: Optional[Path] = None
        for d in unused:
            if d.path != current_path:
                current_path = d.path
                print(f"\n{current_path}")
            print(f"  {d.lineno:5d}  {d.qualname}")

        print(f"\nTotal: {len(unused)} unused in {len({d.path for d in unused})} file(s)")

    elapsed = time.time() - start
    print(
        f"\nScanned {len(index.modules)} modules, {len(reachable)} reachable "
        f"({elapsed:.2f}s)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
