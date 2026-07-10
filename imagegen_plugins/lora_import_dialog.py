#!/usr/bin/env python3
"""Import or edit LoRA metadata; probe compatibility on import."""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressDialog,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from imagegen_plugins.hf_model_ids import lora_model_display_name
from imagegen_plugins.lora_compatibility_checker import probe_lora_on_model
from imagegen_plugins.lora_model_registry import host_id_for_lora_model, klein_lora_model_aliases, lora_probe_model_is_local
from imagegen_plugins.lora_user_entries import (
    build_user_lora_entry,
    display_name_from_path,
    find_user_lora_for_source,
    validate_safetensors_source,
)
from utils import (
    display_to_path,
    normalize_path_for_display,
    show_styled_information,
    show_styled_warning,
)

_FORM_CONTROL_HEIGHT = 32


def _lora_path_for_display(path: str | Path) -> str:
    text = str(path or "").strip()
    if not text:
        return ""
    return normalize_path_for_display(display_to_path(text))


def _lora_path_for_validation(path: str) -> str:
    return display_to_path(str(path or "").strip())


def _pin_row_height(widget: QWidget, *, width_policy=QSizePolicy.Policy.Expanding) -> None:
    widget.setFixedHeight(_FORM_CONTROL_HEIGHT)
    widget.setSizePolicy(width_policy, QSizePolicy.Policy.Fixed)


class _SafetensorsPathLineEdit(QLineEdit):
    """Path field that accepts a single .safetensors file via drag and drop."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setAcceptDrops(True)
        _pin_row_height(self)
        self.setPlaceholderText("Drop a .safetensors file here or paste a path…")

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        path = _path_from_mime(event.mimeData())
        if path is not None:
            event.acceptProposedAction()
            return
        event.ignore()

    def dragMoveEvent(self, event: QDragEnterEvent) -> None:
        path = _path_from_mime(event.mimeData())
        if path is not None:
            event.acceptProposedAction()
            return
        event.ignore()

    def dropEvent(self, event: QDropEvent) -> None:
        path = _path_from_mime(event.mimeData())
        if path is None:
            event.ignore()
            return
        self.setText(_lora_path_for_display(path))
        event.acceptProposedAction()


def _path_from_mime(mime) -> Optional[Path]:
    if not mime.hasUrls():
        return None
    for url in mime.urls():
        if not url.isLocalFile():
            continue
        path = Path(url.toLocalFile())
        if path.suffix.lower() == ".safetensors" and path.is_file():
            return path
    return None


class _ImportLoraWorker(QThread):
    finished_result = Signal(bool, str, object)

    def __init__(
        self,
        *,
        source_path: str,
        display_name: str,
        model_key: str,
        trigger_word: str,
        scale: float,
        comment: str,
        cancel_flag: List[bool],
        reuse_lora_id: Optional[str] = None,
    ) -> None:
        super().__init__()
        self._source_path = source_path
        self._display_name = display_name
        self._model_key = model_key
        self._trigger_word = trigger_word
        self._scale = scale
        self._comment = comment
        self._cancel_flag = cancel_flag
        self._reuse_lora_id = (reuse_lora_id or "").strip() or None
        self._created_new_entry = False

    def _cancelled(self) -> bool:
        return bool(self._cancel_flag[0])

    def _model_already_supported(self, lora_id: str) -> bool:
        from imagegen_plugins.lora_catalog import lora_model_support

        support = lora_model_support().get(lora_id, ())
        aliases = klein_lora_model_aliases(self._model_key)
        return any(m in support for m in aliases)

    def run(self) -> None:
        entry = None
        try:
            if self._cancelled():
                self.finished_result.emit(False, "Cancelled", None)
                return
            source = validate_safetensors_source(self._source_path)
            if not lora_probe_model_is_local(self._model_key):
                raise RuntimeError(
                    f"The base model ({lora_model_display_name(self._model_key)}) "
                    "is not installed locally. Download it first, then import the LoRA."
                )
            host_id = host_id_for_lora_model(self._model_key)
            if not host_id:
                raise ValueError(f"LoRAs are not supported for model {self._model_key!r}.")
            if self._reuse_lora_id:
                from imagegen_plugins.lora_catalog import get_lora_entry
                from imagegen_plugins.image_gen_persistence import update_lora_entry_metadata

                entry = get_lora_entry(self._reuse_lora_id)
                if entry is None:
                    raise ValueError(f"LoRA {self._reuse_lora_id!r} was not found.")
                if entry.host_id != host_id:
                    raise ValueError(
                        "This LoRA file is already imported for a different model family."
                    )
                update_lora_entry_metadata(
                    entry.lora_id,
                    display_name=self._display_name,
                    trigger_word=self._trigger_word or None,
                    scale=self._scale,
                    comment=self._comment or None,
                )
                entry = get_lora_entry(entry.lora_id)
                if entry is None:
                    raise ValueError(f"LoRA {self._reuse_lora_id!r} was not found.")
            else:
                existing = find_user_lora_for_source(source, host_id=host_id)
                if existing is not None:
                    from imagegen_plugins.lora_catalog import get_lora_entry
                    from imagegen_plugins.image_gen_persistence import update_lora_entry_metadata

                    update_lora_entry_metadata(
                        existing.lora_id,
                        display_name=self._display_name,
                        trigger_word=self._trigger_word or None,
                        scale=self._scale,
                        comment=self._comment or None,
                    )
                    entry = get_lora_entry(existing.lora_id)
                    if entry is None:
                        raise ValueError(f"LoRA {existing.lora_id!r} was not found.")
                else:
                    entry = build_user_lora_entry(
                        source_path=source,
                        display_name=self._display_name,
                        model_key=self._model_key,
                        trigger_word=self._trigger_word or None,
                        scale=self._scale,
                        comment=self._comment or None,
                    )
                    self._created_new_entry = True
            from imagegen_plugins.mflux_lora_presets import _assert_mflux_compatible_lora

            _assert_mflux_compatible_lora(
                entry.local_path or "",
                host_id=entry.host_id,
            )
            if not self._model_already_supported(entry.lora_id):
                ok = probe_lora_on_model(
                    self._model_key,
                    entry.local_path or "",
                    entry.scale,
                    self._cancelled,
                    entry=entry,
                )
                if self._cancelled():
                    self.finished_result.emit(False, "Cancelled", entry)
                    return
                if not ok:
                    self.finished_result.emit(
                        False,
                        f"LoRA «{entry.display_name}» failed the compatibility test for "
                        f"{lora_model_display_name(self._model_key)}.",
                        entry,
                    )
                    return
            from imagegen_plugins.image_gen_persistence import register_user_lora

            register_user_lora(
                entry,
                model_key=self._model_key,
                supported_models=[self._model_key],
            )
            self.finished_result.emit(True, "", entry)
        except Exception as exc:
            self.finished_result.emit(False, str(exc), entry)


class LoraEntryDialog(QDialog):
    """Add downloaded LoRA or edit metadata for any catalog entry."""

    def __init__(
        self,
        parent: Optional[QWidget],
        *,
        model_key: str,
        mode: str = "add",
        lora_id: Optional[str] = None,
    ) -> None:
        super().__init__(parent)
        self._model_key = model_key
        self._mode = mode
        self._lora_id = lora_id
        self._edit_entry = None
        if mode == "edit":
            if not lora_id:
                raise ValueError("lora_id is required for edit mode.")
            from imagegen_plugins.lora_catalog import get_lora_entry

            self._edit_entry = get_lora_entry(lora_id)
            if self._edit_entry is None:
                raise ValueError(f"LoRA {lora_id!r} was not found.")

        is_edit = mode == "edit"
        self.setWindowTitle("Edit LoRA" if is_edit else "Add Downloaded LoRA")
        self.setWindowModality(Qt.WindowModality.WindowModal)
        self.resize(580, 340 if is_edit else 320)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(12)
        if is_edit:
            intro = QLabel(
                f"Edit LoRA details for <b>{lora_model_display_name(model_key)}</b>."
            )
        else:
            intro = QLabel(
                f"Import a .safetensors LoRA for <b>{lora_model_display_name(model_key)}</b>. "
                "The file is copied into the app cache and tested before it is added."
            )
        intro.setWordWrap(True)
        layout.addWidget(intro)
        self._intro_label = intro
        self._reuse_lora_id: Optional[str] = None

        form = QFormLayout()
        form.setVerticalSpacing(12)
        form.setHorizontalSpacing(12)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        form.setFormAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)

        self._path_edit = _SafetensorsPathLineEdit(self)
        self._browse_btn = QPushButton("Browse…")
        self._browse_btn.setObjectName("loraImportBrowseButton")
        self._browse_btn.setFixedWidth(96)
        _pin_row_height(self._browse_btn, width_policy=QSizePolicy.Policy.Fixed)
        self._browse_btn.setStyleSheet(
            "QPushButton#loraImportBrowseButton { min-width: 96px; padding: 4px 10px; }"
        )
        self._browse_btn.clicked.connect(self._browse)
        path_row = QHBoxLayout()
        path_row.setContentsMargins(0, 0, 0, 0)
        path_row.setSpacing(8)
        path_row.addWidget(self._path_edit, 1)
        path_row.addWidget(self._browse_btn)
        self._path_wrap = QWidget()
        self._path_wrap.setLayout(path_row)
        self._path_wrap.setFixedHeight(_FORM_CONTROL_HEIGHT)
        self._path_label = "File:"
        form.addRow(self._path_label, self._path_wrap)

        self._name_edit = QLineEdit()
        _pin_row_height(self._name_edit)
        self._name_edit.setPlaceholderText("Display name in LoRA menus")
        form.addRow("Name:", self._name_edit)

        self._trigger_edit = QLineEdit()
        _pin_row_height(self._trigger_edit)
        self._trigger_edit.setPlaceholderText("Optional trigger word for prompts")
        form.addRow("Trigger:", self._trigger_edit)

        self._scale_spin = QDoubleSpinBox()
        _pin_row_height(self._scale_spin, width_policy=QSizePolicy.Policy.Fixed)
        self._scale_spin.setRange(0.1, 2.0)
        self._scale_spin.setSingleStep(0.1)
        self._scale_spin.setValue(1.0)
        form.addRow("Scale:", self._scale_spin)

        self._comment_edit = QLineEdit()
        _pin_row_height(self._comment_edit)
        self._comment_edit.setPlaceholderText("Optional notes (Settings tab only)")
        form.addRow("Comment:", self._comment_edit)
        layout.addLayout(form)
        self._form = form

        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)
        btn_row.addStretch()
        cancel_btn = QPushButton("Cancel")
        _pin_row_height(cancel_btn, width_policy=QSizePolicy.Policy.Fixed)
        cancel_btn.clicked.connect(self.reject)
        self._action_btn = QPushButton("Save" if is_edit else "Test && Add")
        _pin_row_height(self._action_btn, width_policy=QSizePolicy.Policy.Fixed)
        self._action_btn.setDefault(True)
        self._action_btn.clicked.connect(
            self._save_edit if is_edit else self._start_import
        )
        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(self._action_btn)
        layout.addLayout(btn_row)

        if is_edit:
            self._prime_edit_fields()
        else:
            self._path_edit.textChanged.connect(self._on_path_changed)

    def _update_add_intro(self, *, reusing: bool) -> None:
        if self._mode != "add":
            return
        model_label = lora_model_display_name(self._model_key)
        if reusing:
            self._intro_label.setText(
                f"This file is already imported. Adding will enable it for "
                f"<b>{model_label}</b> using the existing LoRA entry."
            )
            return
        self._intro_label.setText(
            f"Import a .safetensors LoRA for <b>{model_label}</b>. "
            "The file is copied into the app cache and tested before it is added."
        )

    def _prime_edit_fields(self) -> None:
        entry = self._edit_entry
        if entry is None:
            return
        path = (entry.local_path or "").strip()
        if path:
            self._path_edit.setText(_lora_path_for_display(path))
            self._path_edit.setReadOnly(True)
            self._path_edit.setAcceptDrops(False)
            self._browse_btn.setEnabled(False)
        else:
            self._form.removeRow(self._path_wrap)
        self._name_edit.setText(entry.display_name)
        self._trigger_edit.setText(entry.trigger_word or "")
        self._scale_spin.setValue(float(entry.scale))
        self._comment_edit.setText(entry.comment or "")

    def _on_path_changed(self, text: str) -> None:
        if self._mode != "add":
            return
        path = (text or "").strip()
        if not path:
            self._reuse_lora_id = None
            self._update_add_intro(reusing=False)
            return
        host_id = host_id_for_lora_model(self._model_key)
        if not host_id:
            return
        resolved_path = _lora_path_for_validation(path)
        try:
            source = validate_safetensors_source(resolved_path)
            display_path = _lora_path_for_display(source)
            if display_path and display_path != path:
                self._set_path_edit_text(display_path)
                path = display_path
            existing = find_user_lora_for_source(source, host_id=host_id)
        except Exception:
            existing = None
            if not self._name_edit.text().strip():
                try:
                    self._name_edit.setText(
                        display_name_from_path(Path(resolved_path).expanduser())
                    )
                except Exception:
                    pass
            self._reuse_lora_id = None
            self._update_add_intro(reusing=False)
            return
        if existing is not None:
            self._reuse_lora_id = existing.lora_id
            self._name_edit.setText(existing.display_name)
            self._trigger_edit.setText(existing.trigger_word or "")
            self._scale_spin.setValue(float(existing.scale))
            self._comment_edit.setText(existing.comment or "")
            self._update_add_intro(reusing=True)
            return
        self._reuse_lora_id = None
        if not self._name_edit.text().strip():
            self._name_edit.setText(display_name_from_path(source))
        self._update_add_intro(reusing=False)

    def _browse(self) -> None:
        from PySide6.QtWidgets import QFileDialog

        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select LoRA weights",
            str(Path.home() / "Downloads"),
            "Safetensors (*.safetensors);;All Files (*)",
        )
        if path:
            self._path_edit.setText(_lora_path_for_display(path))

    def _set_path_edit_text(self, text: str) -> None:
        self._path_edit.blockSignals(True)
        self._path_edit.setText(text)
        self._path_edit.blockSignals(False)

    def _save_edit(self) -> None:
        if self._edit_entry is None or not self._lora_id:
            return
        name = self._name_edit.text().strip()
        if not name:
            show_styled_warning(self, "Edit LoRA", "Enter a display name.")
            return
        from imagegen_plugins.image_gen_persistence import update_lora_entry_metadata

        try:
            update_lora_entry_metadata(
                self._lora_id,
                display_name=name,
                trigger_word=self._trigger_edit.text().strip() or None,
                scale=float(self._scale_spin.value()),
                comment=self._comment_edit.text().strip() or None,
            )
        except ValueError as exc:
            show_styled_warning(self, "Edit LoRA", str(exc))
            return
        except Exception as exc:
            show_styled_warning(self, "Edit LoRA", str(exc))
            return
        show_styled_information(
            self,
            "Edit LoRA",
            f"«{name}» was updated.",
        )
        self.accept()

    def _start_import(self) -> None:
        path = self._path_edit.text().strip()
        name = self._name_edit.text().strip()
        if not path:
            show_styled_warning(self, "Add LoRA", "Choose a .safetensors file.")
            return
        if not name:
            show_styled_warning(self, "Add LoRA", "Enter a display name.")
            return
        resolved_path = _lora_path_for_validation(path)
        try:
            validate_safetensors_source(resolved_path)
        except (OSError, ValueError) as exc:
            show_styled_warning(self, "Add LoRA", str(exc))
            return
        display_path = _lora_path_for_display(resolved_path)
        if display_path and display_path != path:
            self._set_path_edit_text(display_path)

        host_id = host_id_for_lora_model(self._model_key)
        reuse_lora_id = self._reuse_lora_id
        if not reuse_lora_id and host_id:
            try:
                source = validate_safetensors_source(resolved_path)
                existing = find_user_lora_for_source(source, host_id=host_id)
                if existing is not None:
                    reuse_lora_id = existing.lora_id
            except Exception:
                pass
        if reuse_lora_id and host_id:
            from config import get_config
            from imagegen_plugins.lora_catalog_settings import model_state

            st = model_state(get_config().load_settings(), self._model_key)
            enabled = set(st.get("enabled_ids") or [])
            hidden = set(st.get("hidden_ids") or [])
            if reuse_lora_id in enabled and reuse_lora_id not in hidden:
                show_styled_information(
                    self,
                    "Add LoRA",
                    f"«{name}» is already enabled for "
                    f"{lora_model_display_name(self._model_key)}.",
                )
                self.accept()
                return

        progress = QProgressDialog(
            f"Testing LoRA on {lora_model_display_name(self._model_key)}…",
            "Cancel",
            0,
            0,
            self,
        )
        progress.setWindowTitle("Add LoRA")
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(0)
        progress.show()
        QApplication.processEvents()

        cancel_flag: List[bool] = [False]
        progress.canceled.connect(lambda: cancel_flag.__setitem__(0, True))

        worker = _ImportLoraWorker(
            source_path=resolved_path,
            display_name=name,
            model_key=self._model_key,
            trigger_word=self._trigger_edit.text().strip(),
            scale=float(self._scale_spin.value()),
            comment=self._comment_edit.text().strip(),
            cancel_flag=cancel_flag,
            reuse_lora_id=reuse_lora_id,
        )

        def on_done(ok: bool, err: str, entry: object) -> None:
            progress.close()
            if ok:
                show_styled_information(
                    self,
                    "Add LoRA",
                    f"«{getattr(entry, 'display_name', name)}» was added and enabled.",
                )
                self.accept()
                return
            if entry is not None and getattr(worker, "_created_new_entry", False):
                from imagegen_plugins.lora_user_entries import remove_user_lora_files

                remove_user_lora_files(entry)
            if err and err != "Cancelled":
                show_styled_warning(self, "Add LoRA", err)

        worker.finished_result.connect(on_done)
        worker.start()
        self._worker = worker


# Back-compat alias
AddDownloadedLoraDialog = LoraEntryDialog


def run_add_downloaded_lora_dialog(
    parent: Optional[QWidget],
    *,
    model_key: str,
) -> bool:
    """Open import dialog; return True if a LoRA was registered."""
    dlg = LoraEntryDialog(parent, model_key=model_key, mode="add")
    return dlg.exec() == QDialog.DialogCode.Accepted


def run_edit_lora_dialog(
    parent: Optional[QWidget],
    *,
    lora_id: str,
    model_key: str,
) -> bool:
    """Open edit dialog; return True if metadata was saved."""
    try:
        dlg = LoraEntryDialog(
            parent,
            model_key=model_key,
            mode="edit",
            lora_id=lora_id,
        )
    except ValueError as exc:
        show_styled_warning(parent, "Edit LoRA", str(exc))
        return False
    return dlg.exec() == QDialog.DialogCode.Accepted
