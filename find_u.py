#!/usr/bin/env python3
"""
Find unused functions and methods in the Prowser (prowser.py) project.

Uses AST indexing + import-graph reachability from known entry points.
Conservative by design: ambiguous references mark every same-named definition
in reachable modules as used; Qt/plugin hooks are whitelisted explicitly.

Update DYNAMIC_METHOD_NAMES / ENTRY_MODULES / KNOWN_DELEGATE_ATTRS when adding
new subprocess workers, pipeline entry points, manager delegation attrs, or
framework callbacks that are not called by name in code.

Reference detection covers: direct calls, function values (keyword args, assigns,
containers), Qt signal .connect targets, QTimer.singleShot callbacks, getattr string
names, delegate attribute chains (self.main_window.*, self.sidebar_manager.*),
and inherited methods resolved via self.* / super() on subclasses.
"""

from __future__ import annotations

import argparse
import ast
import sys
import time
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import DefaultDict, Dict, Iterable, Iterator, List, Optional, Set, Tuple

SCRIPT_VERSION = "1.2.0"

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
    # PyInstaller runtime hook (imports frozen_support helpers at bundle startup).
    "pyinstaller_runtime_hook",
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
        "focusNextPrevChild",
        "hitButton",
        "singleStep",
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

# Instance attribute names mapped to (module, class) for delegate call resolution.
# Update when managers/handlers are renamed or new delegation attrs are introduced.
KNOWN_DELEGATE_ATTRS: Dict[str, Tuple[str, str]] = {
    "main_window": ("image_browser_window", "ImageBrowserWindow"),
    "configuration_sync_manager": (
        "browser_window.managers.configuration_sync_manager",
        "ConfigurationSyncManager",
    ),
    "sidebar_manager": ("browser_window.managers.sidebar_manager", "SidebarManager"),
    "view_mode_manager": ("browser_window.managers.view_mode_manager", "ViewModeManager"),
    "selection_manager": ("browser_window.managers.selection_manager", "SelectionManager"),
    "navigation_manager": ("browser_window.managers.navigation_manager", "NavigationManager"),
    "browse_view_handler": ("files.browse_view_handler", "BrowseViewHandler"),
    "browser_controller": ("browser_window.infra.browser_controller", "BrowserController"),
    "file_tree_handler": ("files.file_tree_handler", "FileTreeHandler"),
    "refresh_manager": ("browser_window.managers.refresh_manager", "RefreshManager"),
    "ui_layout_manager": ("browser_window.managers.ui_layout_manager", "UILayoutManager"),
    "rename_status_manager": ("files.rename_status_manager", "RenameStatusManager"),
    "list_view_container": ("thumbnails.list_canvas", "ListCanvas"),
    "thumbnail_container": ("thumbnails.view_manager", "ViewManager"),
    "event_bus": ("event_bus", "EventBus"),
}


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
        # (module, class_name) -> resolved (module, class_name) bases
        self.class_bases: Dict[Tuple[str, str], List[Tuple[str, str]]] = {}
        self._parse_all()
        self._build_class_bases()

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

    def _build_class_bases(self) -> None:
        for module, info in self.modules.items():
            for node in ast.walk(info.tree):
                if not isinstance(node, ast.ClassDef):
                    continue
                bases: List[Tuple[str, str]] = []
                for base_expr in node.bases:
                    resolved = self._resolve_base_expr(
                        module, info.imports, info.classes, base_expr
                    )
                    if resolved is not None:
                        bases.append(resolved)
                self.class_bases[(module, node.name)] = bases

    @staticmethod
    def _resolve_base_expr(
        module: str,
        imports: Dict[str, ImportBinding],
        local_classes: Dict[str, bool],
        node: ast.expr,
    ) -> Optional[Tuple[str, str]]:
        if isinstance(node, ast.Name):
            if node.id in local_classes:
                return (module, node.id)
            binding = imports.get(node.id)
            if binding is not None and binding.name is not None:
                return (binding.module, binding.name)
            return None
        if isinstance(node, ast.Attribute):
            binding = None
            if isinstance(node.value, ast.Name):
                binding = imports.get(node.value.id)
            if binding is not None and binding.name is not None:
                return (binding.module, node.attr)
        return None

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
        self.dynamic_names: Set[str] = set()  # getattr string literals (project-wide)
        self.ambiguous_names: Set[str] = set()  # unresolved attr tails (same module only)
        self._class_stack: List[str] = []
        self._local_classes: Set[str] = set(self.info.classes)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        for dec in node.decorator_list:
            self._visit_decorator(dec)
        self._class_stack.append(node.name)
        self._local_classes.add(node.name)
        self.generic_visit(node)
        self._class_stack.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        for dec in node.decorator_list:
            self._visit_decorator(dec)
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        for dec in node.decorator_list:
            self._visit_decorator(dec)
        self.generic_visit(node)

    def _visit_decorator(self, node: ast.AST) -> None:
        if isinstance(node, ast.Name):
            self._resolve_name(node.id, call=True)
        elif isinstance(node, ast.Attribute):
            self._visit_attribute(node, call=True)
        elif isinstance(node, ast.Call):
            self._visit_decorator(node.func)
            for arg in node.args:
                self._visit_decorator(arg)

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
        elif self._is_timer_singleshot_call(node) and len(node.args) >= 2:
            self._visit_connect_target(node.args[1])
        for arg in node.args:
            self._visit_value_ref(arg)
        for kw in node.keywords:
            self._visit_value_ref(kw.value)
        self.generic_visit(node)

    def _is_timer_singleshot_call(self, node: ast.Call) -> bool:
        func = node.func
        return isinstance(func, ast.Attribute) and func.attr == "singleShot"

    def _visit_value_ref(self, node: ast.AST) -> None:
        if isinstance(node, ast.Name):
            self._resolve_name(node.id, call=True)
        elif isinstance(node, ast.Attribute):
            self._visit_attribute(node, call=True)
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr in {"partial", "method"} and node.args:
                self._visit_value_ref(node.args[0])

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

    def visit_Name(self, node: ast.Name) -> None:
        if isinstance(node.ctx, ast.Load):
            self._resolve_name(node.id, call=False)
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if not isinstance(node.ctx, ast.Load):
            self.generic_visit(node)
            return
        if isinstance(node.value, ast.Call):
            # e.g. job_queue_cell_background_qcolor(settings).darker(112)
            self.generic_visit(node.value)
            return
        if isinstance(node.value, ast.Name) and node.value.id == "super":
            self._mark_current_class_method(node.attr)
            return
        self._visit_attribute(node, call=False)
        self.generic_visit(node)

    def visit_Assign(self, node: ast.Assign) -> None:
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        self.generic_visit(node)

    def visit_Return(self, node: ast.Return) -> None:
        if node.value is not None:
            self._visit_value_ref(node.value)
        self.generic_visit(node)

    def _resolve_delegate_method(
        self, node: ast.Attribute
    ) -> Optional[Tuple[str, str, str]]:
        """Resolve self.<delegate>.method or <delegate>.method to a concrete class method."""
        method_name = node.attr
        base = node.value
        if isinstance(base, ast.Attribute):
            if isinstance(base.value, ast.Name) and base.value.id == "self":
                delegate_attr = base.attr
                target = KNOWN_DELEGATE_ATTRS.get(delegate_attr)
                if target is not None:
                    return (*target, method_name)
        if isinstance(base, ast.Name):
            target = KNOWN_DELEGATE_ATTRS.get(base.id)
            if target is not None:
                return (*target, method_name)
        return None

    def _visit_attribute(self, node: ast.Attribute, call: bool) -> None:
        delegate = self._resolve_delegate_method(node)
        if delegate is not None:
            mod, cls, method = delegate
            self._mark_method_inherited(mod, cls, method)
            return
        name = node.attr
        value = node.value
        if isinstance(value, ast.Name):
            if value.id == "self" and self._class_stack:
                self._mark_method_on_class_and_subclasses(
                    self.module, self._class_stack[-1], name
                )
                return
            if value.id == "cls" and self._class_stack:
                self._mark_method_on_class_and_subclasses(
                    self.module, self._class_stack[-1], name
                )
                return
            if value.id == "super" and self._class_stack:
                self._mark_method_on_class_and_subclasses(
                    self.module, self._class_stack[-1], name
                )
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
                self._mark_method_inherited(self.module, value.id, name)
                return
            if value.id in self.info.classes:
                self._mark_method_inherited(self.module, value.id, name)
                return
        self.ambiguous_names.add(name)

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

    def _mark_method(self, class_name: str, method_name: str) -> bool:
        key = (self.module, f"{class_name}.{method_name}")
        if key in self.index.def_by_key:
            self.used_keys.add(key)
            return True
        return False

    def _mark_method_inherited(
        self, module: str, class_name: str, method_name: str
    ) -> bool:
        key = (module, f"{class_name}.{method_name}")
        if key in self.index.def_by_key:
            self.used_keys.add(key)
            return True
        for base_mod, base_cls in self.index.class_bases.get((module, class_name), []):
            if self._mark_method_inherited(base_mod, base_cls, method_name):
                return True
        return False

    def _mark_method_on_class_and_subclasses(
        self, module: str, class_name: str, method_name: str
    ) -> None:
        """Resolve self.method() including overrides on subclasses (virtual dispatch)."""
        if self._mark_method_inherited(module, class_name, method_name):
            return
        _propagate_method_to_subclasses(
            self.index, self.used_keys, module, class_name, method_name
        )

    def _mark_current_class_method(self, method_name: str) -> None:
        if self._class_stack:
            self._mark_method_on_class_and_subclasses(
                self.module, self._class_stack[-1], method_name
            )

    def _mark_module_attr(self, module: str, attr: str) -> None:
        key = (module, attr)
        if key in self.index.def_by_key:
            self.used_keys.add(key)
            return
        info = self.index.modules.get(module)
        if info is None:
            return
        binding = info.imports.get(attr)
        if binding is None:
            return
        if binding.name is not None:
            self._mark_module_attr(binding.module, binding.name)
        else:
            self._mark_module_attr(binding.module, attr)


def _subclasses_of(
    index: ProjectIndex, module: str, class_name: str
) -> List[Tuple[str, str]]:
    """Direct and indirect subclasses of (module, class_name) within the index."""
    children: DefaultDict[Tuple[str, str], List[Tuple[str, str]]] = defaultdict(list)
    for (mod, cls), bases in index.class_bases.items():
        for base_mod, base_cls in bases:
            children[(base_mod, base_cls)].append((mod, cls))

    out: List[Tuple[str, str]] = []
    stack = list(children.get((module, class_name), []))
    seen: Set[Tuple[str, str]] = set()
    while stack:
        item = stack.pop()
        if item in seen:
            continue
        seen.add(item)
        out.append(item)
        stack.extend(children.get(item, []))
    return out


def _propagate_method_to_subclasses(
    index: ProjectIndex,
    used: Set[Tuple[str, str]],
    module: str,
    class_name: str,
    method_name: str,
) -> None:
    """Mark method overrides on subclasses when a base/mixin calls self.method()."""
    for sub_mod, sub_cls in _subclasses_of(index, module, class_name):
        key = (sub_mod, f"{sub_cls}.{method_name}")
        if key in index.def_by_key:
            used.add(key)


def _propagate_used_to_overrides(
    index: ProjectIndex, used: Set[Tuple[str, str]], reachable: Set[str]
) -> None:
    """Mark subclass overrides used when a base-class method is used (virtual calls)."""
    changed = True
    while changed:
        changed = False
        for d in index.def_by_key.values():
            if d.key in used or d.module not in reachable or not d.is_method:
                continue
            class_name, _, method_name = d.qualname.partition(".")
            if not method_name:
                continue
            for base_mod, base_cls in index.class_bases.get((d.module, class_name), []):
                if (base_mod, f"{base_cls}.{method_name}") in used:
                    used.add(d.key)
                    changed = True
                    break


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


def _mark_import_shadow_fallbacks(
    index: ProjectIndex, reachable: Set[str], used: Set[Tuple[str, str]]
) -> None:
    """Mark try/except import fallback defs that share a name with a live import."""
    for module in reachable:
        info = index.modules[module]
        local_funcs = {
            d.name
            for d in info.defs
            if not d.is_method and not d.is_nested
        }
        if not local_funcs:
            continue
        for node in ast.walk(info.tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
                continue
            name = node.func.id
            if name in info.imports and name in local_funcs:
                key = (module, name)
                if key in index.def_by_key:
                    used.add(key)


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

    _mark_import_shadow_fallbacks(index, reachable, used)

    for name in dynamic_names:
        for d in index.defs_by_name.get(name, []):
            if d.module in reachable:
                used.add(d.key)

    for scanner in scanners:
        for name in scanner.ambiguous_names:
            for d in index.defs_by_name.get(name, []):
                if d.module in reachable:
                    used.add(d.key)

    _propagate_used_to_overrides(index, used, reachable)
    # Also propagate base/mixin usage down to subclass overrides.
    for key in list(used):
        mod, qual = key
        if "." not in qual:
            continue
        cls, method = qual.split(".", 1)
        _propagate_method_to_subclasses(index, used, mod, cls, method)

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
