#!/usr/bin/env python3
"""Tools > Debug > Check LoRAs — progress UI and background worker."""

from __future__ import annotations

import html
from typing import Any, Dict, List, Optional

from PySide6.QtCore import QThread, Signal, Qt
from PySide6.QtWidgets import QApplication, QLabel, QProgressDialog

from config import get_config
from imagegen_plugins.lora_catalog import (
    LORA_CATALOG,
    LORA_MODEL_ABBREV,
    catalog_entries_for_settings,
    probe_models_for_lora_entry,
)
from imagegen_plugins.lora_host_registry import lora_hosts_for_settings

FLUX_LORA_CATALOG = LORA_CATALOG
from imagegen_plugins.image_gen_persistence import save_lora_catalog_state
from imagegen_plugins.lora_compatibility_checker import (
    LoraCheckStats,
    run_lora_compatibility_check,
)
from imagegen_plugins.pipelines.mflux_schnell import mflux_is_installed
from utils import show_styled_information, show_styled_warning


def _format_stats_html(stats: LoraCheckStats) -> str:
    return (
        f"LoRAs: {stats.supported_loras} supported, "
        f"{stats.removed_loras} removed, "
        f"{stats.skipped_loras} skipped (download/error) · "
        f"Probes: {stats.probes_done}/{stats.probes_total}"
    )


def _progress_html(
    phase: str,
    lora_id: str,
    model_key: str,
    stats: LoraCheckStats,
) -> str:
    entry = FLUX_LORA_CATALOG.get(lora_id)
    lora_label = entry.display_name if entry else lora_id
    if phase == "download":
        line2 = f"Downloading / resolving weights for <b>{html.escape(lora_label)}</b>"
    else:
        model_label = LORA_MODEL_ABBREV.get(model_key, model_key)
        line2 = (
            f"Testing <b>{html.escape(lora_label)}</b> on "
            f"<b>{html.escape(model_label)}</b>"
        )
    lines = [line2, _format_stats_html(stats)]
    return "".join(
        f'<p style="margin:0 0 0.4em 0">{line}</p>' for line in lines
    )


def run_check_loras_dialog(parent) -> None:
    """Tools > Debug > Check LoRAs."""
    if not mflux_is_installed():
        show_styled_warning(
            parent,
            "Check LoRAs",
            "MFLUX is not installed. Install with: pip install mflux",
        )
        return

    settings = get_config().load_settings()
    entries = []
    for host in lora_hosts_for_settings():
        entries.extend(catalog_entries_for_settings(settings, host.host_id))
    if not entries:
        show_styled_information(
            parent,
            "Check LoRAs",
            "No LoRAs are visible in Settings → LoRA. "
            "Restore hidden entries or add catalog entries first.",
        )
        return

    probes_total = sum(len(probe_models_for_lora_entry(e)) for e in entries)
    if probes_total == 0:
        show_styled_information(
            parent,
            "Check LoRAs",
            "No LoRA/model probe combinations are configured for the visible list.",
        )
        return

    progress_label = QLabel(
        _progress_html("download", entries[0].lora_id, "", LoraCheckStats(probes_total=probes_total))
    )
    progress_label.setAlignment(Qt.AlignmentFlag.AlignLeft)
    progress_label.setTextFormat(Qt.TextFormat.RichText)

    progress = QProgressDialog("", "Cancel", 0, max(1, probes_total), parent)
    progress.setLabel(progress_label)
    progress.setWindowTitle("Check LoRAs")
    progress.setWindowModality(Qt.WindowModality.WindowModal)
    progress.setMinimumDuration(0)
    progress.setValue(0)
    progress.resize(520, 160)
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
            _progress_html(phase, lora_id, model_key, stats)
        )
        total = max(1, probe_total)
        progress.setMaximum(total)
        val = probe_idx if phase == "probe" else min(probe_idx, total - 1)
        progress.setValue(min(val, total))
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

        from imagegen_plugins.lora_compatibility_checker import LoraCheckResult

        if not isinstance(result, LoraCheckResult):
            return

        if result.cancelled:
            show_styled_information(parent, "Check LoRAs", "Cancelled.")
            return

        save_lora_catalog_state(model_support=result.model_support)
        settings = get_config().load_settings()

        mw = parent
        if hasattr(mw, "refresh_open_imagegen_lora_combos"):
            mw.refresh_open_imagegen_lora_combos()

        sd = getattr(mw, "settings_dialog", None)
        if sd is not None and getattr(sd, "isVisible", lambda: False)():
            from imagegen_plugins.lora_catalog_settings import (
                enabled_lora_ids_for_model,
                hidden_lora_ids_for_model,
            )

            model_key = (
                sd._current_lora_model_key()
                if hasattr(sd, "_current_lora_model_key")
                else "dev"
            )
            if hasattr(sd, "_lora_hidden_ids"):
                sd._lora_hidden_ids = set(hidden_lora_ids_for_model(model_key, settings))
            if hasattr(sd, "_rebuild_lora_settings_grid"):
                sd._rebuild_lora_settings_grid()
            if hasattr(sd, "_apply_lora_settings_to_widgets"):
                sd._apply_lora_settings_to_widgets(
                    list(enabled_lora_ids_for_model(model_key, settings))
                )

        st = result.stats
        lines = [
            f"Catalog entries checked: {st.loras_total}",
            f"Passed probe: {st.supported_loras}",
            f"Failed probe: {st.removed_loras}",
            f"Skipped (download/error): {st.skipped_loras}",
            f"Probes run: {st.probes_done}/{st.probes_total}",
            "",
            "Only LoRAs that passed the probe for a base model appear in Settings → LoRA "
            "and in that model’s generation LoRA menu (after enable + install).",
            "",
            "Re-run Check LoRAs after installing new weights. Use Hide in Settings to "
            "remove a passing LoRA you do not want listed.",
        ]
        show_styled_information(parent, "Check LoRAs", "\n".join(lines))

    worker = LoraCheckWorker(parent)
    worker.progress_signal.connect(on_progress)
    worker.finished_result.connect(on_finished)
    worker.start()
