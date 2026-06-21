#!/usr/bin/env python3
"""Tools > Debug > List Models — browse cached Hugging Face and LM Studio models."""

from __future__ import annotations

import base64
import json
from functools import lru_cache
import re
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, FrozenSet, Iterable, List, Optional, Set, Tuple

from huggingface_hub import scan_cache_dir

from PySide6.QtCore import QEvent, QObject, QThread, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QGuiApplication, QIcon, QImage, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from theme.theme_base import asset_path
from theme.theme_service import get_active_theme
from utils import present_auxiliary_dialog, raise_dialog_without_space_hop

_WEIGHT_SUFFIXES = (".safetensors", ".bin", ".pt", ".ckpt")
_PIPELINE_MARKERS = (
    "diffusion_pytorch",
    "scheduler_config",
    "/unet/",
    "/text_encoder/",
    "/transformer/",
    "/vae/",
)
_IMAGE_REPO_HINTS = (
    "sdxl",
    "stable-diffusion",
    "diffusers",
    "realvis",
    "realistic_vision",
    "/realistic_",
    "sana",
    "z-image",
    "anythingfurry",
    "anything-v",
    "turbo",
    "openflux",
)
_FLUX_BASE_HINTS = ("flux.1", "flux.2", "flux1", "flux2", "/flux-", "_flux_")
_LORA_FILENAME_HINTS = ("lora", "adapter_model", "pytorch_lora_weights", "lycoris")
_INCIDENTAL_SUFFIXES = (
    ".md",
    ".txt",
    ".webp",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".svg",
    ".mp4",
    ".html",
    ".csv",
    ".zip",
)
_INCIDENTAL_EXACT = frozenset(
    {
        ".gitattributes",
        "readme.md",
        "license",
        "license.md",
        "license.txt",
        "usage.md",
        "config.toml",
    }
)
_LORA_MAX_SINGLE_WEIGHT_BYTES = 2_000_000_000
_IMAGE_NAME_HINT_MIN_BYTES = 500_000_000
_FLUX_NAME_IMAGE_MIN_BYTES = 1_000_000_000

_VAE_RE = re.compile(r"(?:^|/|-)vae(?:$|/|-)")


def repo_files(repo) -> Tuple[Set[str], Dict[str, str]]:
    names: Set[str] = set()
    paths: Dict[str, str] = {}
    for rev in repo.revisions:
        for f in rev.files:
            key = f.file_name.lower()
            names.add(key)
            paths[key] = f.file_path
    return names, paths


def _load_json(path: Optional[str]):
    if not path:
        return None
    try:
        with open(path) as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError):
        return None


def load_config_jsons(paths: Dict[str, str]) -> List[dict]:
    configs: List[dict] = []
    for name, path in paths.items():
        if name == "config.json":
            cfg = _load_json(path)
            if cfg:
                configs.append(cfg)
    return configs


def weight_file_names(names: Iterable[str]) -> List[str]:
    return sorted(n for n in names if n.endswith(_WEIGHT_SUFFIXES))


def is_incidental_file(name: str) -> bool:
    lower = name.lower()
    if lower in _INCIDENTAL_EXACT:
        return True
    base = lower.rsplit("/", 1)[-1]
    if base in _INCIDENTAL_EXACT:
        return True
    if base.endswith(_INCIDENTAL_SUFFIXES):
        return True
    if lower.startswith(("images/", "assets/", "preview/")):
        return True
    return False


def has_diffusers_pipeline(names: Set[str]) -> bool:
    if "model_index.json" in names:
        return True
    return any(
        marker in name for name in names for marker in _PIPELINE_MARKERS
    )


def _is_vae_repo(repo_lower: str) -> bool:
    return bool(_VAE_RE.search(repo_lower))


def is_standalone_vae(names: Set[str], configs: List[dict], repo_lower: str) -> bool:
    if _is_vae_repo(repo_lower):
        return True
    return (
        any(cfg.get("_class_name") == "AutoencoderKL" for cfg in configs)
        and len(names) <= 3
        and "model_index.json" not in names
    )


@lru_cache(maxsize=1)
def known_lora_repo_ids() -> FrozenSet[str]:
    try:
        from imagegen_plugins.lora_catalog import LORA_CATALOG

        return frozenset(
            e.repo_id.lower()
            for e in LORA_CATALOG.values()
            if e.repo_id
        )
    except Exception:
        return frozenset()


def is_known_lora_repo(repo_id: str) -> bool:
    return repo_id.lower() in known_lora_repo_ids()


def is_in_app_lora_cache(repo_id: str) -> bool:
    slug = repo_id.replace("/", "__")
    for root in (
        Path.home() / ".cache" / "image_browser" / "mflux_loras",
        Path.home() / ".cache" / "mflux_loras",
    ):
        cache_dir = root / slug
        if cache_dir.is_dir() and any(cache_dir.glob("*.safetensors")):
            return True
    return False


def weight_names_suggest_lora(weight_names: List[str]) -> bool:
    return any(
        hint in w for w in weight_names for hint in _LORA_FILENAME_HINTS
    )


def config_suggests_full_model(configs: List[dict]) -> bool:
    for cfg in configs:
        class_name = str(cfg.get("_class_name", ""))
        if any(
            k in class_name
            for k in ("UNet", "Transformer2D", "Pipeline", "AutoencoderKLFlux")
        ):
            return True
    return False


def looks_like_lora_adapter(
    names: Set[str],
    configs: List[dict],
    repo_id: str,
    repo_lower: str,
    size_on_disk: int,
) -> bool:
    if has_diffusers_pipeline(names):
        return False
    if is_known_lora_repo(repo_id) or is_in_app_lora_cache(repo_id):
        return True
    if "lora" in repo_lower:
        return True

    weights = weight_file_names(names)
    if not weights:
        return False

    if weight_names_suggest_lora(weights):
        return True

    if config_suggests_full_model(configs):
        return False

    if "adapter_config.json" in names:
        return True

    non_incidental = {n for n in names if not is_incidental_file(n)}
    if len(weights) == 1 and len(non_incidental) <= 2:
        if size_on_disk < _LORA_MAX_SINGLE_WEIGHT_BYTES:
            return True

    return False


def name_suggests_image_checkpoint(repo_lower: str, size_on_disk: int) -> bool:
    if size_on_disk < _IMAGE_NAME_HINT_MIN_BYTES:
        return False
    if any(h in repo_lower for h in _IMAGE_REPO_HINTS):
        return True
    if any(h in repo_lower for h in _FLUX_BASE_HINTS):
        return True
    if "flux" in repo_lower and size_on_disk >= _FLUX_NAME_IMAGE_MIN_BYTES:
        return True
    return False


def infer_model_kind(repo) -> str:
    if repo.repo_type != "model":
        return repo.repo_type

    names, paths = repo_files(repo)
    repo_lower = repo.repo_id.lower()
    configs = load_config_jsons(paths)
    size_on_disk = int(getattr(repo, "size_on_disk", 0) or 0)

    if "controlnet" in repo_lower or any("controlnet" in n for n in names):
        return "ControlNet"
    if (
        "ip-adapter" in repo_lower
        or "ip_adapter" in repo_lower
        or any("ip-adapter" in n or "ip_adapter" in n for n in names)
    ):
        return "Adapter"
    if any(x in repo_lower for x in ("tts", "whisper", "speech", "kyutai/")):
        return "Audio"
    if is_standalone_vae(names, configs, repo_lower):
        return "VAE"

    if looks_like_lora_adapter(names, configs, repo.repo_id, repo_lower, size_on_disk):
        return "LoRA"

    if has_diffusers_pipeline(names):
        return "image"
    if any(
        marker in n
        for n in names
        for marker in ("diffusion_pytorch", "scheduler_config", "/unet/", "/transformer/")
    ):
        return "image"
    if config_suggests_full_model(configs):
        return "image"
    if name_suggests_image_checkpoint(repo_lower, size_on_disk):
        return "image"

    for cfg in configs:
        model_type = str(cfg.get("model_type", ""))
        archs = cfg.get("architectures") or []
        if model_type == "clip" or any("CLIP" in a for a in archs):
            return "CLIP"

    for cfg in configs:
        archs = cfg.get("architectures") or []
        model_type = str(cfg.get("model_type", ""))
        if any("CausalLM" in a or "ForConditionalGeneration" in a for a in archs):
            return "text"
        if model_type in ("llama", "qwen2", "qwen3", "mistral", "gemma", "phi", "gpt2", "bloom"):
            return "text"

    weights = weight_file_names(names)
    non_incidental = {n for n in names if not is_incidental_file(n)}
    if (
        len(weights) == 1
        and len(non_incidental) <= 2
        and size_on_disk < _LORA_MAX_SINGLE_WEIGHT_BYTES
    ):
        return "LoRA"

    return "other"

_FOLDER_ROLE = Qt.ItemDataRole.UserRole + 1
_FULL_NAME_ROLE = Qt.ItemDataRole.UserRole + 2
_DELETE_BTN_SIZE = 24


def _display_model_name(full_name: str, strip_org_prefix: bool) -> str:
    if strip_org_prefix and "/" in full_name:
        return full_name.split("/", 1)[1]
    return full_name


def _full_name_from_item(item: QTableWidgetItem) -> str:
    stored = item.data(_FULL_NAME_ROLE)
    if stored:
        return str(stored)
    return item.text()


def _get_saved_lm_model_key() -> str:
    try:
        from imagegen_plugins.lmstudio_caption import _get_last_lm_model_key

        return _get_last_lm_model_key() or ""
    except Exception:
        return ""


def _delete_button_stylesheet() -> str:
    t = get_active_theme()
    icon_url = f"url({asset_path('trash_icon.png')})"
    hover_url = f"url({asset_path('trash_icon_hover.png')})"
    sz = _DELETE_BTN_SIZE
    return f"""
        QPushButton {{
            background-color: {t.dialog_background_hex};
            border: 1px solid {t.border_default_hex};
            border-radius: 3px;
            padding: 0px;
            min-width: {sz}px;
            max-width: {sz}px;
            min-height: {sz}px;
            max-height: {sz}px;
            image: {icon_url};
        }}
        QPushButton:focus {{
            border: 1px solid {t.current_image_border_color_hex};
            outline: none;
        }}
        QPushButton:hover {{
            background-color: {t.tab_button_hover_bg_hex};
            border: 1px solid {t.tab_button_hover_bg_hex};
            image: {hover_url};
        }}
        QPushButton:pressed {{
            background-color: {t.sidebar_splitter_handle_hex};
        }}
        QPushButton:disabled {{
            opacity: 0.35;
        }}
    """


def _make_delete_button(on_click) -> QPushButton:
    btn = QPushButton()
    btn.setToolTip("Delete")
    btn.setStyleSheet(_delete_button_stylesheet())
    btn.setFixedSize(_DELETE_BTN_SIZE, _DELETE_BTN_SIZE)
    btn.clicked.connect(on_click)
    return btn

_CLEAR_FILTER_ICON_WEBP_B64 = (
    "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"
)


def _clear_filter_icon() -> QIcon:
    data = base64.b64decode(_CLEAR_FILTER_ICON_WEBP_B64)
    pixmap = QPixmap()
    pixmap.loadFromData(data, "WEBP")
    return QIcon(pixmap)

SCRIPT_DIR = Path(__file__).resolve().parent
LM_MODEL_EXTENSIONS = {".gguf", ".safetensors", ".bin", ".pt"}


def resolve_lmstudio_models_dir() -> Path:
    """Return the LM Studio models directory (first existing candidate)."""
    candidates = [
        Path.home() / ".cache" / "lm-studio" / "models",
        Path.home() / ".lmstudio" / "models",
        SCRIPT_DIR / "cache" / "lmstudio" / "models",
    ]
    for path in candidates:
        if path.is_dir():
            return path
    return candidates[0]

_QUANT_RE = re.compile(
    r"(?:^|[-_.])((?:q\d+(?:_[a-z0-9]+)+|q\d+_[0-9]|fp16|bf16|f16|f32))(?:[-_.]|$)",
    re.IGNORECASE,
)


class NumericSortItem(QTableWidgetItem):
    """Table item that sorts by a numeric value instead of display text."""

    def __init__(self, text: str, sort_value):
        super().__init__(text)
        self._sort_value = sort_value

    def __lt__(self, other):
        if isinstance(other, NumericSortItem):
            return self._sort_value < other._sort_value
        return super().__lt__(other)


@dataclass(frozen=True)
class LMStudioModel:
    path: Path
    model_id: str
    filename: str
    format: str
    quant: str
    kind: str
    size_bytes: int
    mtime: float


def _format_size(size_bytes: int) -> str:
    if size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    if size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
    return f"{size_bytes / (1024 * 1024 * 1024):.1f} GB"


def _path_mtime(path: Path) -> float | None:
    try:
        return path.stat().st_mtime
    except OSError:
        return None


def _most_recent_mtime(*paths: Path) -> float:
    mtimes = [t for p in paths if p for t in (_path_mtime(p),) if t is not None]
    return max(mtimes) if mtimes else 0.0


def _format_mtime(ts: float) -> str:
    if ts <= 0:
        return "—"
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")


def hf_repo_most_recent_mtime(repo) -> float:
    """Return the latest mtime among the repo cache dir and its cached files."""
    paths: list[Path] = []
    cache_dir = hf_repo_cache_dir(repo)
    if cache_dir:
        paths.append(cache_dir)
    for rev in repo.revisions:
        for f in rev.files:
            paths.append(Path(f.file_path))
    return _most_recent_mtime(*paths)


def lm_model_most_recent_mtime(path: Path) -> float:
    """Return the latest mtime of the model file and its containing directory."""
    return _most_recent_mtime(path, path.parent)


def infer_lm_quantization(filename: str) -> str:
    match = _QUANT_RE.search(filename)
    if not match:
        return ""
    return match.group(1).upper().replace(".", "_")


def infer_lm_model_kind(name_lower: str) -> str:
    if "lora" in name_lower or "adapter" in name_lower:
        return "LoRA"
    if "embed" in name_lower:
        return "Embedding"
    if "vision" in name_lower or "mmproj" in name_lower or "clip" in name_lower:
        return "Vision"
    if "whisper" in name_lower or "speech" in name_lower:
        return "Audio"
    return "LLM"


def _lm_model_id(rel_path: Path) -> str:
    parts = rel_path.parts
    if len(parts) >= 3:
        return f"{parts[0]}/{parts[1]}"
    if len(parts) == 2:
        return parts[0]
    return rel_path.stem


def hf_repo_cache_dir(repo) -> Path | None:
    """Return the Hugging Face hub cache folder for a cached repo."""
    for rev in repo.revisions:
        for f in rev.files:
            path = Path(f.file_path)
            for parent in path.parents:
                if parent.name.startswith("models--"):
                    return parent
    return None


def scan_lmstudio_models() -> list[LMStudioModel]:
    models_dir = resolve_lmstudio_models_dir()
    if not models_dir.is_dir():
        return []

    models: list[LMStudioModel] = []
    for path in sorted(models_dir.rglob("*")):
        if not path.is_file():
            continue
        suffix = path.suffix.lower()
        if suffix not in LM_MODEL_EXTENSIONS:
            continue
        rel = path.relative_to(models_dir)
        name_lower = str(rel).lower()
        models.append(
            LMStudioModel(
                path=path,
                model_id=_lm_model_id(rel),
                filename=path.name,
                format=suffix.lstrip(".").upper(),
                quant=infer_lm_quantization(path.name),
                kind=infer_lm_model_kind(name_lower),
                size_bytes=path.stat().st_size,
                mtime=lm_model_most_recent_mtime(path),
            )
        )
    return models


class ListModelsWindow(QDialog):
    def __init__(
        self,
        parent=None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Cached Models")
        self.resize(960, 520)
        self.setWindowFlags(
            Qt.WindowType.Dialog
            | Qt.WindowType.WindowTitleHint
            | Qt.WindowType.WindowSystemMenuHint
            | Qt.WindowType.WindowCloseButtonHint
        )
        self.setWindowModality(Qt.WindowModality.NonModal)

        layout = QVBoxLayout(self)

        header = QHBoxLayout()

        self.status_label = QLabel()
        header.addWidget(self.status_label, stretch=1)

        refresh_btn = QPushButton("Refresh")
        refresh_btn.clicked.connect(self.load_models)
        header.addWidget(refresh_btn)

        filter_widget = QWidget()
        filter_layout = QHBoxLayout(filter_widget)
        filter_layout.setContentsMargins(0, 0, 0, 0)
        filter_layout.setSpacing(4)

        self.filter_edit = QLineEdit()
        self.filter_edit.setPlaceholderText("Filter models…")
        self.filter_edit.setMinimumWidth(220)
        self.filter_edit.textChanged.connect(self._apply_filter)

        self.filter_clear_btn = QPushButton()
        self.filter_clear_btn.setIcon(_clear_filter_icon())
        self.filter_clear_btn.setIconSize(QSize(18, 18))
        self.filter_clear_btn.setFixedSize(24, 24)
        self.filter_clear_btn.setFlat(True)
        self.filter_clear_btn.setToolTip("Clear filter")
        self.filter_clear_btn.setEnabled(False)
        self.filter_clear_btn.clicked.connect(self.filter_edit.clear)
        self.filter_edit.textChanged.connect(
            lambda text: self.filter_clear_btn.setEnabled(bool(text))
        )

        filter_layout.addWidget(self.filter_edit)
        filter_layout.addWidget(self.filter_clear_btn)
        header.addWidget(filter_widget)

        self.format_btn = QPushButton("Format")
        self.format_btn.setCheckable(True)
        self.format_btn.setToolTip(
            "Toggle short names (hide publisher prefix before the slash)"
        )
        self.format_btn.toggled.connect(self._on_format_toggled)
        header.addWidget(self.format_btn)

        layout.addLayout(header)

        self._strip_org_prefix = False
        self.tabs = QTabWidget()
        self.tabs.setTabPosition(QTabWidget.TabPosition.West)
        self.hf_table = self._create_table(["Filename", "Type", "Size", "Modified", ""])
        self.lms_table = self._create_table(
            ["Model", "Type", "Format", "Quant", "Size", "Modified", ""]
        )
        self.tabs.addTab(self.hf_table, "Hugging Face")
        self.tabs.addTab(self.lms_table, "LM Studio")
        self.tabs.currentChanged.connect(self._on_tab_changed)
        layout.addWidget(self.tabs)

        self._hf_total_size = 0
        self._lms_total_size = 0
        self._lms_models_dir = resolve_lmstudio_models_dir()
        self.load_models()

    def _create_table(self, headers: list[str]) -> QTableWidget:
        table = QTableWidget(0, len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.verticalHeader().setVisible(False)
        table.setSortingEnabled(True)

        header_view = table.horizontalHeader()
        header_view.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for col in range(1, len(headers) - 1):
            header_view.setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)
        header_view.setSectionResizeMode(len(headers) - 1, QHeaderView.ResizeMode.ResizeToContents)
        table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        table.customContextMenuRequested.connect(
            lambda pos, t=table: self._show_row_context_menu(t, pos)
        )
        return table

    def _show_row_context_menu(self, table: QTableWidget, pos):
        row = table.rowAt(pos.y())
        if row < 0 or table.isRowHidden(row):
            return
        name_item = table.item(row, 0)
        if not name_item:
            return

        model_name = _full_name_from_item(name_item)
        folder = name_item.data(_FOLDER_ROLE)

        is_lms = table is self.lms_table
        kind = ""
        if is_lms:
            type_item = table.item(row, 1)
            kind = type_item.text() if type_item else ""

        menu = QMenu(self)
        use_action = None
        if is_lms and kind == "LLM":
            use_action = menu.addAction("Use")
        copy_action = menu.addAction("Copy Model Name")
        finder_action = menu.addAction("Open in Finder")
        finder_action.setEnabled(bool(folder))

        action = menu.exec(table.viewport().mapToGlobal(pos))
        if use_action and action == use_action:
            _use_llm_model(self, model_name)
        elif action == copy_action:
            from copy_feedback import copy_text_to_clipboard

            copy_text_to_clipboard(model_name, anchor=table.viewport())
        elif action == finder_action and folder:
            self._open_in_finder(folder)

    def _open_in_finder(self, folder: str):
        try:
            subprocess.run(["open", folder], check=True, timeout=5)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError) as exc:
            QMessageBox.warning(
                self,
                "Open in Finder",
                f"Could not open {folder} in Finder:\n{exc}",
            )

    def _on_format_toggled(self, checked: bool) -> None:
        self._strip_org_prefix = checked
        self._refresh_name_display()

    def _refresh_name_display(self) -> None:
        for table in (self.hf_table, self.lms_table):
            for row in range(table.rowCount()):
                item = table.item(row, 0)
                if not item:
                    continue
                full_name = _full_name_from_item(item)
                item.setText(_display_model_name(full_name, self._strip_org_prefix))

    def _on_tab_changed(self, _index: int):
        self._apply_filter()
        self._update_status()

    def _row_matches_filter(self, table: QTableWidget, row: int, needle: str) -> bool:
        for col in range(table.columnCount() - 1):
            item = table.item(row, col)
            if not item:
                continue
            if needle in item.text().lower():
                return True
            full_name = item.data(_FULL_NAME_ROLE)
            if full_name and needle in str(full_name).lower():
                return True
            extra = item.data(Qt.ItemDataRole.UserRole)
            if extra and needle in str(extra).lower():
                return True
        return False

    def _apply_filter(self):
        table = self.hf_table if self.tabs.currentIndex() == 0 else self.lms_table
        needle = self.filter_edit.text().strip().lower()
        for row in range(table.rowCount()):
            if not needle:
                table.setRowHidden(row, False)
            else:
                table.setRowHidden(row, not self._row_matches_filter(table, row, needle))
        self._update_status()

    def _visible_row_count(self, table: QTableWidget) -> int:
        return sum(1 for row in range(table.rowCount()) if not table.isRowHidden(row))

    def _update_status(self):
        if self.tabs.currentIndex() == 0:
            table = self.hf_table
            total = table.rowCount()
            visible = self._visible_row_count(table)
            total_size = _format_size(self._hf_total_size)
            if visible == total:
                self.status_label.setText(f"{total} cached repos, {total_size} total")
            else:
                self.status_label.setText(
                    f"{visible} of {total} cached repos shown, {total_size} total"
                )
        else:
            table = self.lms_table
            total = table.rowCount()
            visible = self._visible_row_count(table)
            total_size = _format_size(self._lms_total_size)
            if visible == total:
                self.status_label.setText(f"{total} LM Studio models, {total_size} total")
            else:
                self.status_label.setText(
                    f"{visible} of {total} LM Studio models shown, {total_size} total"
                )

    def load_models(self):
        self._load_hf_models()
        self._load_lmstudio_models()
        self._apply_filter()

    def _load_hf_models(self):
        self.hf_table.setSortingEnabled(False)
        self.hf_table.setRowCount(0)

        cache_info = scan_cache_dir()
        repos = sorted(cache_info.repos, key=lambda r: r.repo_id.lower())
        self._hf_total_size = cache_info.size_on_disk

        self.hf_table.setRowCount(len(repos))
        for row, repo in enumerate(repos):
            full_name = repo.repo_id
            name_item = QTableWidgetItem(
                _display_model_name(full_name, self._strip_org_prefix)
            )
            name_item.setData(_FULL_NAME_ROLE, full_name)
            name_item.setData(Qt.ItemDataRole.UserRole, repo.repo_id)
            cache_dir = hf_repo_cache_dir(repo)
            if cache_dir:
                name_item.setData(_FOLDER_ROLE, str(cache_dir))

            type_item = QTableWidgetItem(infer_model_kind(repo))

            size_item = NumericSortItem(repo.size_on_disk_str, repo.size_on_disk)
            size_item.setTextAlignment(
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            )

            mtime = hf_repo_most_recent_mtime(repo)
            modified_item = NumericSortItem(_format_mtime(mtime), mtime)

            self.hf_table.setItem(row, 0, name_item)
            self.hf_table.setItem(row, 1, type_item)
            self.hf_table.setItem(row, 2, size_item)
            self.hf_table.setItem(row, 3, modified_item)

            delete_btn = _make_delete_button(
                lambda _checked=False, r=repo: self.confirm_delete_hf(r)
            )
            self.hf_table.setCellWidget(row, 4, delete_btn)

        self.hf_table.setSortingEnabled(True)

    def _load_lmstudio_models(self):
        self.lms_table.setSortingEnabled(False)
        self.lms_table.setRowCount(0)

        self._lms_models_dir = resolve_lmstudio_models_dir()
        models = scan_lmstudio_models()
        self._lms_total_size = sum(model.size_bytes for model in models)

        saved_key = _get_saved_lm_model_key()
        try:
            from gemma4_voice_vision_demo import _model_keys_match
        except Exception:
            _model_keys_match = None

        self.lms_table.setRowCount(len(models))
        for row, model in enumerate(models):
            rel_path = model.path.relative_to(self._lms_models_dir)
            full_name = model.model_id
            model_item = QTableWidgetItem(
                _display_model_name(full_name, self._strip_org_prefix)
            )
            model_item.setToolTip(str(rel_path))
            model_item.setData(_FULL_NAME_ROLE, full_name)
            model_item.setData(Qt.ItemDataRole.UserRole, f"{rel_path} {model.filename}")
            model_item.setData(_FOLDER_ROLE, str(model.path.parent))
            if (
                saved_key
                and _model_keys_match is not None
                and _model_keys_match(saved_key, full_name)
            ):
                bold_font = QFont(model_item.font())
                bold_font.setBold(True)
                model_item.setFont(bold_font)

            type_item = QTableWidgetItem(model.kind)
            format_item = QTableWidgetItem(model.format)
            quant_item = QTableWidgetItem(model.quant or "—")

            size_str = _format_size(model.size_bytes)
            size_item = NumericSortItem(size_str, model.size_bytes)
            size_item.setTextAlignment(
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            )

            modified_item = NumericSortItem(_format_mtime(model.mtime), model.mtime)

            self.lms_table.setItem(row, 0, model_item)
            self.lms_table.setItem(row, 1, type_item)
            self.lms_table.setItem(row, 2, format_item)
            self.lms_table.setItem(row, 3, quant_item)
            self.lms_table.setItem(row, 4, size_item)
            self.lms_table.setItem(row, 5, modified_item)

            delete_btn = _make_delete_button(
                lambda _checked=False, m=model: self.confirm_delete_lm(m)
            )
            self.lms_table.setCellWidget(row, 6, delete_btn)

        self.lms_table.setSortingEnabled(True)

    def confirm_delete_hf(self, repo):
        reply = QMessageBox.question(
            self,
            "Delete Model",
            (
                f"Delete cached {repo.repo_type} '{repo.repo_id}'?\n\n"
                f"This will free {repo.size_on_disk_str}."
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        revision_hashes = [rev.commit_hash for rev in repo.revisions]
        if not revision_hashes:
            QMessageBox.warning(
                self,
                "Delete Failed",
                f"No cached revisions found for '{repo.repo_id}'.",
            )
            return

        try:
            scan_cache_dir().delete_revisions(*revision_hashes).execute()
        except Exception as exc:
            QMessageBox.critical(
                self,
                "Delete Failed",
                f"Could not delete '{repo.repo_id}':\n{exc}",
            )
            return

        self.load_models()

    def confirm_delete_lm(self, model: LMStudioModel):
        size_str = _format_size(model.size_bytes)
        rel_path = model.path.relative_to(self._lms_models_dir)
        reply = QMessageBox.question(
            self,
            "Delete Model",
            (
                f"Delete LM Studio model file?\n\n"
                f"{rel_path}\n\n"
                f"This will free {size_str}."
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        try:
            model.path.unlink()
            parent = model.path.parent
            while parent != self._lms_models_dir and parent.is_dir() and not any(parent.iterdir()):
                parent.rmdir()
                parent = parent.parent
        except Exception as exc:
            QMessageBox.critical(
                self,
                "Delete Failed",
                f"Could not delete '{rel_path}':\n{exc}",
            )
            return

        self.load_models()



_CLEAR_ICON_DATA_URI = (
    "data:image/webp;base64,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"
)
_CLEAR_ICON_DISPLAY_PX = 18
_CLEAR_ICON_HOVER_BRIGHTEN = 1.45

_window: Optional[QWidget] = None


def _clear_icon_source_pixmap() -> QPixmap:
    _, _, payload = _CLEAR_ICON_DATA_URI.partition(",")
    pixmap = QPixmap()
    if not pixmap.loadFromData(base64.b64decode(payload), "WEBP"):
        return QPixmap()
    return pixmap


def _scaled_clear_icon_pixmap(icon_px: int) -> QPixmap:
    pixmap = _clear_icon_source_pixmap()
    if pixmap.isNull():
        return QPixmap()
    return pixmap.scaled(
        icon_px,
        icon_px,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )


def _brighten_pixmap(pixmap: QPixmap, factor: float = _CLEAR_ICON_HOVER_BRIGHTEN) -> QPixmap:
    image = pixmap.toImage().convertToFormat(QImage.Format.Format_ARGB32)
    for y in range(image.height()):
        for x in range(image.width()):
            color = QColor(image.pixelColor(x, y))
            if color.alpha() == 0:
                continue
            image.setPixelColor(
                x,
                y,
                QColor(
                    min(255, int(color.red() * factor)),
                    min(255, int(color.green() * factor)),
                    min(255, int(color.blue() * factor)),
                    color.alpha(),
                ),
            )
    return QPixmap.fromImage(image)


class _ClearFilterButtonHoverIcon(QObject):
    def __init__(self, button: QPushButton, normal_icon: QIcon, hover_icon: QIcon):
        super().__init__(button)
        self._button = button
        self._normal_icon = normal_icon
        self._hover_icon = hover_icon
        button.installEventFilter(self)

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        if obj is self._button:
            if event.type() == QEvent.Type.HoverEnter:
                self._button.setIcon(self._hover_icon)
            elif event.type() == QEvent.Type.HoverLeave:
                self._button.setIcon(self._normal_icon)
        return False


def _clear_filter_icon_size_px() -> int:
    pixmap = _clear_icon_source_pixmap()
    if pixmap.isNull():
        return _CLEAR_ICON_DISPLAY_PX
    return min(pixmap.width(), pixmap.height(), _CLEAR_ICON_DISPLAY_PX)


def _configure_filter_clear_button(window: QWidget) -> None:
    """Override app-wide QPushButton min-width for the filter clear icon button."""
    btn = getattr(window, "filter_clear_btn", None)
    if btn is None:
        return

    icon_px = _clear_filter_icon_size_px()
    btn_px = icon_px + 6

    btn.setObjectName("listModelsFilterClearBtn")
    icon_pixmap = _scaled_clear_icon_pixmap(icon_px)
    normal_icon = QIcon(icon_pixmap)
    hover_icon = QIcon(_brighten_pixmap(icon_pixmap))
    btn.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
    btn.setIcon(normal_icon)
    btn.setIconSize(QSize(icon_px, icon_px))
    btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
    btn.setFixedSize(btn_px, btn_px)
    _ClearFilterButtonHoverIcon(btn, normal_icon, hover_icon)

    theme = get_active_theme()
    btn.setStyleSheet(
        f"""
        QPushButton#listModelsFilterClearBtn {{
            padding: 0px;
            min-width: {btn_px}px;
            max-width: {btn_px}px;
            min-height: {btn_px}px;
            max-height: {btn_px}px;
            border-radius: 3px;
            border: 1px solid {theme.border_default_hex};
            background-color: {theme.dialog_background_hex};
        }}
        QPushButton#listModelsFilterClearBtn:hover {{
            background-color: {theme.tab_button_hover_bg_hex};
            border: 1px solid {theme.tab_button_hover_bg_hex};
        }}
        QPushButton#listModelsFilterClearBtn:disabled {{
            opacity: 0.35;
        }}
        """
    )


def _on_window_destroyed() -> None:
    global _window
    _window = None


def _use_llm_model(window: QWidget, model_id: str) -> None:
    """Load an LLM in LM Studio and persist it as the caption default."""
    model_id = model_id.strip()
    if not model_id:
        return

    progress = QProgressDialog(
        f"Loading {model_id} in LM Studio…",
        None,
        0,
        0,
        window,
    )
    progress.setWindowTitle("Use LLM")
    progress.setWindowModality(Qt.WindowModality.WindowModal)
    progress.setMinimumDuration(0)
    progress.setCancelButton(None)
    progress.show()

    class _LoadWorker(QThread):
        status = Signal(str)
        finished_ok = Signal(str)
        finished_err = Signal(str)

        def __init__(self, target_model_id: str):
            super().__init__()
            self._model_id = target_model_id

        def run(self):
            try:
                from config import get_config
                from gemma4_voice_vision_demo import (
                    ensure_lms_model_loaded,
                    resolve_lms_load_key,
                )

                load_key = resolve_lms_load_key(self._model_id)

                def emit_status(msg: str) -> None:
                    self.status.emit(msg)

                loaded_id = ensure_lms_model_loaded(
                    load_key,
                    status_cb=emit_status,
                )
                get_config().update_setting(
                    "caption_last_lm_model_key",
                    load_key,
                )
                self.finished_ok.emit(loaded_id or load_key)
            except Exception as exc:
                self.finished_err.emit(str(exc))

    def on_finished_ok(loaded_id: str) -> None:
        progress.close()
        if hasattr(window, "_load_lmstudio_models"):
            window._load_lmstudio_models()
            window._apply_filter()
        QMessageBox.information(
            window,
            "Use LLM",
            f"Loaded and set as default LLM:\n\n{loaded_id}\n\n(model: {model_id})",
        )

    def on_finished_err(err: str) -> None:
        progress.close()
        QMessageBox.warning(
            window,
            "Use LLM",
            f"Could not load {model_id!r}:\n\n{err}",
        )

    worker = _LoadWorker(model_id)
    worker.status.connect(progress.setLabelText)
    worker.finished_ok.connect(on_finished_ok)
    worker.finished_err.connect(on_finished_err)
    worker.finished.connect(worker.deleteLater)
    worker.start()
    window._use_llm_worker = worker


def run_list_models_window(parent: Optional[QWidget] = None) -> QWidget:
    """Open (or raise) the cached models browser."""
    global _window

    if _window is not None:
        try:
            if _window.isVisible():
                raise_dialog_without_space_hop(_window)
                return _window
        except RuntimeError:
            _window = None

    window = ListModelsWindow(parent)
    _configure_filter_clear_button(window)
    window.setAttribute(Qt.WA_DeleteOnClose, True)
    window.destroyed.connect(_on_window_destroyed)
    _window = window
    present_auxiliary_dialog(window)
    return window
