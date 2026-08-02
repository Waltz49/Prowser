#!/usr/bin/env python3
"""Tools > Debug > Check LoRAs — progress UI and background worker."""

from __future__ import annotations

import html
from typing import List

from PySide6.QtCore import QThread, Signal, Qt
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QPlainTextEdit,
    QProgressDialog,
    QVBoxLayout,
)

from config import get_config
from imagegen_plugins.hf_model_ids import FLUX1_DEV, lora_model_display_name
from imagegen_plugins.lora_catalog import (
    LORA_CATALOG,
    get_lora_entry,
    lora_choice_label,
)
from imagegen_plugins.image_gen_persistence import save_lora_catalog_state
from imagegen_plugins.lora_compatibility_checker import (
    LoraCheckChange,
    LoraCheckResult,
    LoraCheckStats,
    installed_probeable_models,
    plan_disk_lora_probes,
    run_lora_compatibility_check,
)
from utils import (
    get_button_style,
    get_dialog_shell_stylesheet,
    show_styled_information,
    show_styled_warning,
)

FLUX_LORA_CATALOG = LORA_CATALOG


def _lora_label(lora_id: str) -> str:
    entry = get_lora_entry(lora_id) or FLUX_LORA_CATALOG.get(lora_id)
    return lora_choice_label(entry) if entry else lora_id


def _format_progress_html(
    phase: str,
    lora_id: str,
    model_key: str,
    stats: LoraCheckStats,
) -> str:
    lines: List[str] = []
    if phase == "scan":
        lines.append("<b>Scanning on-disk LoRAs and ~/Downloads…</b>")
        if stats.loras_total or stats.skipped_not_on_disk or stats.downloads_scanned:
            lines.append(
                f"To test: <b>{stats.loras_total}</b> · "
                f"Not on disk (skipped): {stats.skipped_not_on_disk} · "
                f"Installed models: <b>{stats.models_total}</b>"
            )
            if stats.downloads_scanned:
                lines.append(
                    f"Downloads scanned: {stats.downloads_scanned} · "
                    f"Duplicates removed: {stats.downloads_deduped}"
                )
            lines.append(f"Total probes: <b>{stats.probes_total}</b>")
    elif phase == "downloads":
        lines.append("<b>Removing duplicate Downloads LoRAs…</b>")
        lines.append(
            f"Downloads scanned: {stats.downloads_scanned} · "
            f"Duplicates removed: <b>{stats.downloads_deduped}</b>"
        )
    else:
        lora_label = html.escape(_lora_label(lora_id)) if lora_id else "—"
        model_label = (
            html.escape(lora_model_display_name(model_key)) if model_key else "—"
        )
        lora_pos = f"{stats.lora_index}/{max(1, stats.loras_total)}"
        model_pos = (
            f"{stats.model_index_for_lora}/{max(1, stats.models_for_lora)}"
            if stats.models_for_lora
            else "—"
        )
        current = stats.probe_current or max(1, stats.probes_done)
        probe_pos = f"{current}/{max(1, stats.probes_total)}"
        lines.append(
            f"Model <b>{model_pos}</b> · "
            f"LoRA <b>{lora_pos}</b> on this model · "
            f"Probe <b>{probe_pos}</b> "
            f"({stats.probes_done} finished)"
        )
        lines.append(f"Testing <b>{model_label}</b> with <b>{lora_label}</b>")
        if stats.last_result == "pass":
            lines.append("Last result: <span style='color:#1a7f37'>pass</span>")
        elif stats.last_result == "fail":
            lines.append("Last result: <span style='color:#c0392b'>fail</span>")
        lines.append(
            f"Installed models in plan: {stats.models_total} · "
            f"Passed LoRAs: {stats.supported_loras} · "
            f"Newly enabled: {stats.newly_enabled_count} · "
            f"Failed probes: {stats.failed_probe_count}"
        )
    return "".join(f'<p style="margin:0 0 0.35em 0">{line}</p>' for line in lines)


def _changes_of(result: LoraCheckResult, kind: str) -> List[LoraCheckChange]:
    return [c for c in result.changes if c.kind == kind]


def _format_results_text_sections(result: LoraCheckResult) -> List[str]:
    st = result.stats
    lines = [
        (
            "Check LoRAs cancelled (partial results saved)."
            if result.cancelled
            else "Check LoRAs finished."
        ),
        "",
        "Summary",
        f"  On-disk LoRAs tested: {st.loras_done}/{st.loras_total}",
        f"  Installed models: {st.models_total}",
        f"  Probes run: {st.probes_done}/{st.probes_total}",
        f"  LoRAs with at least one pass: {st.supported_loras}",
        f"  LoRAs with no pass: {st.removed_loras}",
        f"  Newly compatible pairs: {st.newly_supported_count}",
        f"  Newly enabled in Settings: {st.newly_enabled_count}",
        f"  Failed probes: {st.failed_probe_count}",
        f"  Skipped (not on disk): {st.skipped_not_on_disk}",
        f"  Skipped (hidden — not enabled): {st.skipped_hidden_count}",
    ]
    if st.downloads_scanned:
        lines.append(f"  Downloads scanned: {st.downloads_scanned}")
        lines.append(f"  Downloads duplicates removed: {st.downloads_deduped}")
        lines.append(f"  Downloads registered: {st.downloads_registered}")
        lines.append(f"  Downloads with no passing model: {st.downloads_failed}")
    if st.skipped_model_probes:
        lines.append(
            f"  Base models not installed (not probed): {st.skipped_model_probes}"
        )

    newly_enabled = _changes_of(result, "newly_enabled")
    newly_supported = _changes_of(result, "newly_supported")
    failed = _changes_of(result, "failed")
    lost = _changes_of(result, "lost_support")
    hidden = _changes_of(result, "skipped_hidden")
    not_disk = _changes_of(result, "skipped_not_on_disk")
    downloads_registered = _changes_of(result, "downloads_registered")
    downloads_deduped = _changes_of(result, "downloads_deduped")
    downloads_failed = _changes_of(result, "downloads_failed")
    enabled_keys = {(c.lora_id, c.model_key) for c in newly_enabled}
    hidden_keys = {(c.lora_id, c.model_key) for c in hidden}
    compat_only = [
        c
        for c in newly_supported
        if (c.lora_id, c.model_key) not in enabled_keys
        and (c.lora_id, c.model_key) not in hidden_keys
    ]

    def add_section(
        title: str,
        items: List[LoraCheckChange],
        *,
        with_model: bool = True,
        limit: int = 250,
    ) -> None:
        if not items:
            return
        lines.append("")
        lines.append(f"{title} ({len(items)})")
        for c in items[:limit]:
            if with_model and c.model_label:
                lines.append(f"  • {c.lora_label} → {c.model_label}")
            else:
                lines.append(f"  • {c.lora_label}")
        if len(items) > limit:
            lines.append(f"  … and {len(items) - limit} more")

    add_section("Newly enabled", newly_enabled)
    add_section("Downloads registered", downloads_registered)
    add_section("Newly compatible (not newly enabled)", compat_only)
    add_section("Failed probes", failed)
    add_section("Lost prior compatibility", lost)
    add_section("Passed but hidden (left disabled)", hidden)
    add_section("Downloads duplicates removed", downloads_deduped, with_model=False)
    add_section("Downloads with no passing model", downloads_failed, with_model=False)
    add_section("Skipped — weights not on disk", not_disk, with_model=False, limit=80)

    lines.extend(
        [
            "",
            "Each on-disk LoRA is probed against every installed base model. Passing "
            "pairs are recorded and enabled in Settings → LoRA (unless previously Hidden).",
            "Unregistered .safetensors in ~/Downloads are tested too; duplicates "
            "(same md5 as an installed LoRA) are deleted from Downloads.",
            "Re-run after downloading new LoRA weights. Use Hide in Settings to "
            "keep a LoRA out of the menus.",
        ]
    )
    return lines


def _show_results_dialog(parent, result: LoraCheckResult) -> None:
    text = "\n".join(_format_results_text_sections(result))
    dlg = QDialog(parent)
    dlg.setWindowTitle("Check LoRAs — Results")
    dlg.setWindowModality(Qt.WindowModality.WindowModal)
    dlg.resize(640, 520)
    dlg.setStyleSheet(get_dialog_shell_stylesheet() + get_button_style())
    layout = QVBoxLayout(dlg)
    layout.setContentsMargins(16, 14, 16, 14)
    layout.setSpacing(10)
    intro = QLabel("Changes from this Check LoRAs run:")
    intro.setWordWrap(True)
    layout.addWidget(intro)
    body = QPlainTextEdit()
    body.setReadOnly(True)
    body.setPlainText(text)
    layout.addWidget(body, 1)
    buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
    buttons.accepted.connect(dlg.accept)
    layout.addWidget(buttons)
    dlg.exec()


def _apply_check_result(parent, result: LoraCheckResult) -> None:
    if result.model_support or result.by_model:
        save_lora_catalog_state(
            model_support=result.model_support or None,
            by_model=result.by_model or None,
        )
    settings = get_config().load_settings()
    mw = parent
    if hasattr(mw, "refresh_open_imagegen_lora_combos"):
        mw.refresh_open_imagegen_lora_combos()

    sd = getattr(mw, "settings_dialog", None)
    if sd is not None and getattr(sd, "isVisible", lambda: False)():
        from imagegen_plugins.lora_catalog_settings import enabled_lora_ids_for_model

        model_key = (
            sd._current_lora_model_key()
            if hasattr(sd, "_current_lora_model_key")
            else FLUX1_DEV
        )
        if hasattr(sd, "_rebuild_lora_settings_grid"):
            sd._rebuild_lora_settings_grid()
        if hasattr(sd, "_apply_lora_settings_to_widgets"):
            sd._apply_lora_settings_to_widgets(
                list(enabled_lora_ids_for_model(model_key, settings))
            )


def run_check_loras_dialog(parent) -> None:
    """Tools > Debug > Check LoRAs — probe LoRAs; enable and register where they pass."""
    if not installed_probeable_models():
        show_styled_warning(
            parent,
            "Check LoRAs",
            "No installed base models were found to probe LoRAs against.\n\n"
            "Install at least one image-generation base model, then run Check LoRAs again.",
        )
        return

    settings = get_config().load_settings()
    _candidates, plan, plan_stats = plan_disk_lora_probes(settings, dedupe=False)
    if not plan:
        show_styled_information(
            parent,
            "Check LoRAs",
            "Nothing to probe.\n\n"
            f"Catalog candidates considered: {len(_candidates)}\n"
            f"Skipped (not on disk): {plan_stats.skipped_not_on_disk}\n"
            f"Downloads scanned: {plan_stats.downloads_scanned}\n"
            f"Downloads duplicates removed: {plan_stats.downloads_deduped}\n\n"
            "Download LoRA weights (or place .safetensors in ~/Downloads), install a "
            "base model, then run Check LoRAs again.",
        )
        return

    probes_total = plan_stats.probes_total
    progress_label = QLabel(_format_progress_html("scan", "", "", plan_stats))
    progress_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
    progress_label.setTextFormat(Qt.TextFormat.RichText)
    progress_label.setWordWrap(True)
    progress_label.setMinimumWidth(520)

    progress = QProgressDialog("", "Cancel", 0, max(1, probes_total), parent)
    progress.setLabel(progress_label)
    progress.setWindowTitle("Check LoRAs")
    progress.setWindowModality(Qt.WindowModality.WindowModal)
    progress.setMinimumDuration(0)
    progress.setAutoClose(False)
    progress.setAutoReset(False)
    progress.setValue(0)
    progress.resize(560, 220)
    progress.show()
    QApplication.processEvents()

    cancel_flag: List[bool] = [False]
    progress.canceled.connect(lambda: cancel_flag.__setitem__(0, True))

    def cancel_check() -> bool:
        return bool(cancel_flag[0])

    class LoraCheckWorker(QThread):
        progress_signal = Signal(int, int, str, str, str, object)
        finished_result = Signal(object)

        def run(self) -> None:
            cfg = get_config().load_settings()

            def report(
                probe_idx: int,
                probe_total: int,
                phase: str,
                lora_id: str,
                model_key: str,
                stats: LoraCheckStats,
            ) -> None:
                self.progress_signal.emit(
                    probe_idx,
                    probe_total,
                    phase,
                    lora_id,
                    model_key,
                    stats,
                )

            try:
                result = run_lora_compatibility_check(
                    cfg,
                    progress_callback=report,
                    cancel_check=cancel_check,
                )
            except Exception as e:
                print(f"[Check LoRAs] fatal error: {e}")
                import traceback

                traceback.print_exc()
                result = None
            self.finished_result.emit(result)

    def on_progress(
        probe_idx: int,
        probe_total: int,
        phase: str,
        lora_id: str,
        model_key: str,
        stats_obj: object,
    ) -> None:
        stats = stats_obj if isinstance(stats_obj, LoraCheckStats) else LoraCheckStats()
        progress_label.setText(
            _format_progress_html(phase, lora_id, model_key, stats)
        )
        total = max(1, probe_total)
        progress.setMaximum(total)
        if phase == "probe":
            # Advance when a probe starts so the bar moves during long runs.
            current = stats.probe_current or max(0, probe_idx)
            val = min(max(0, current), total)
        else:
            val = 0
        progress.setValue(val)
        QApplication.processEvents()

    def on_finished(result: object) -> None:
        progress.close()
        if result is None:
            show_styled_warning(
                parent,
                "Check LoRAs",
                "Check failed with an error. See Tools > Debug > View log.",
            )
            return

        if not isinstance(result, LoraCheckResult):
            return

        if result.cancelled and result.stats.probes_done == 0:
            show_styled_information(parent, "Check LoRAs", "Cancelled.")
            return

        _apply_check_result(parent, result)
        _show_results_dialog(parent, result)

    worker = LoraCheckWorker(parent)
    # Keep the QThread alive for the duration of the run.
    progress._lora_check_worker = worker  # type: ignore[attr-defined]
    worker.progress_signal.connect(on_progress)
    worker.finished_result.connect(on_finished)
    worker.start()
