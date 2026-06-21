#!/usr/bin/env python3
"""Probe LoRA compatibility per model family (minimal MFLUX generation)."""

from __future__ import annotations

import os
from prowser_temp_files import prowser_mkstemp_path
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

from imagegen_plugins.hf_model_ids import (
    FLUX1_DEV,
    FLUX1_FILL_DEV,
    FLUX1_SCHNELL,
    FLUX2_KLEIN_4B,
    FLUX2_KLEIN_9B,
    FLUX2_KLEIN_9B_KV,
)
from imagegen_plugins.lora_catalog import (
    FluxLoraEntry,
    catalog_entries_for_settings,
    lora_model_support,
    lora_probe_prompt,
    probe_models_for_lora_entry,
)
from imagegen_plugins.lora_model_registry import lora_probe_model_is_local
from imagegen_plugins.lora_host_registry import (
    HOST_FLUX2_KLEIN,
    lora_hosts_for_settings,
)


@dataclass
class LoraCheckStats:
    loras_total: int = 0
    probes_done: int = 0
    probes_total: int = 0
    supported_loras: int = 0
    removed_loras: int = 0
    skipped_loras: int = 0
    skipped_model_probes: int = 0

    def as_dict(self) -> Dict[str, int]:
        return {
            "loras_total": self.loras_total,
            "probes_done": self.probes_done,
            "probes_total": self.probes_total,
            "supported_loras": self.supported_loras,
            "removed_loras": self.removed_loras,
            "skipped_loras": self.skipped_loras,
            "skipped_model_probes": self.skipped_model_probes,
        }


def count_local_lora_probes(entries: List[FluxLoraEntry]) -> int:
    """Probe count for progress UI (installed base models only)."""
    return sum(
        sum(1 for m in probe_models_for_lora_entry(e) if lora_probe_model_is_local(m))
        for e in entries
    )


@dataclass
class LoraCheckResult:
    model_support: Dict[str, List[str]] = field(default_factory=dict)
    hidden_by_host: Dict[str, List[str]] = field(default_factory=dict)
    stats: LoraCheckStats = field(default_factory=LoraCheckStats)
    cancelled: bool = False

    @property
    def deleted_ids(self) -> List[str]:
        """Flat list of hidden ids (all hosts) for back-compat."""
        out: List[str] = []
        for ids in self.hidden_by_host.values():
            out.extend(ids)
        return sorted(set(out))


def is_lora_incompatibility_error(exc: BaseException) -> bool:
    """True when failure is likely LoRA/model mismatch (not OOM, etc.)."""
    msg = f"{type(exc).__name__}: {exc}".lower()
    needles = (
        "not compatible with mflux",
        "wrong key layout",
        "xflabs-style",
        "could not find target path",
        "lora_unet_",
        "lora likely incompatible",
        "diffusion_model.",
        "double_blocks.",
    )
    if any(n in msg for n in needles):
        return True
    if "broadcast_shapes" in msg and ("3072" in msg or "4096" in msg):
        return True
    if "lora" in msg and (
        "matmul" in msg
        or "shape" in msg
        or "incompatible" in msg
        or "unexpected" in msg
        or "broadcast" in msg
    ):
        return True
    return False


def _probe_t2i(
    *,
    hf_model: str,
    lora_path: str,
    lora_scale: float,
    cancel_check: Callable[[], bool],
    prompt: str = "test",
) -> bool:
    from imagegen_plugins.pipelines.mflux_schnell import (
        align_mflux_dims,
        run_mflux_flux_schnell_generate,
    )

    if cancel_check():
        return False
    w, h = align_mflux_dims(256, 256)
    out_path = prowser_mkstemp_path(prefix="lora-probe-", suffix=".png")
    try:
        try:
            os.unlink(out_path)
        except OSError:
            pass
        run_mflux_flux_schnell_generate(
            prompt=prompt,
            width=w,
            height=h,
            steps=2,  # MFLUX scheduler divides by (steps - 1); steps=1 raises ZeroDivisionError
            guidance=0.0,
            seed=42,
            model=hf_model,
            quantize=3,
            mflux_output_path=out_path,
            low_ram=True,
            lora_paths=[lora_path],
            lora_scales=[lora_scale],
        )
        return True
    except Exception as e:
        if is_lora_incompatibility_error(e):
            return False
        raise
    finally:
        try:
            if os.path.isfile(out_path):
                os.unlink(out_path)
        except OSError:
            pass


def _probe_fill(
    *,
    lora_path: str,
    lora_scale: float,
    cancel_check: Callable[[], bool],
    prompt: str = "test",
) -> bool:
    from PIL import Image, ImageDraw

    from imagegen_plugins.pipelines.mflux_fill_expand import _run_mflux_fill_cli

    if cancel_check():
        return False
    w, h = 128, 128
    img = Image.new("RGB", (w, h), (90, 90, 90))
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).rectangle([w // 4, h // 4, 3 * w // 4, 3 * h // 4], fill=255)
    img_path = prowser_mkstemp_path(prefix="lora-probe-fill-", suffix=".png")
    mask_path = prowser_mkstemp_path(prefix="lora-probe-fill-mask-", suffix=".png")
    out_path = prowser_mkstemp_path(prefix="lora-probe-fill-out-", suffix=".png")
    try:
        img.save(img_path)
        mask.save(mask_path)
        try:
            os.unlink(out_path)
        except OSError:
            pass
        _run_mflux_fill_cli(
            image_path=img_path,
            mask_path=mask_path,
            output_path=out_path,
            prompt=prompt,
            width=w,
            height=h,
            steps=8,
            guidance=30.0,
            seed=42,
            quantize=4,
            low_ram=True,
            lora_paths=[lora_path],
            lora_scales=[lora_scale],
        )
        return os.path.isfile(out_path) and os.path.getsize(out_path) >= 64
    except Exception as e:
        if is_lora_incompatibility_error(e):
            return False
        raise
    finally:
        img.close()
        mask.close()
        for p in (img_path, mask_path, out_path):
            try:
                if os.path.isfile(p):
                    os.unlink(p)
            except OSError:
                pass


def _probe_klein_edit(
    *,
    hf_model_id: str,
    lora_path: str,
    lora_scale: float,
    cancel_check: Callable[[], bool],
    prompt: str = "test edit",
) -> bool:
    from PIL import Image

    from imagegen_plugins.mflux_flux2_klein_session import generate_flux2_klein_edit

    if cancel_check():
        return False
    w, h = 256, 256
    img_path = prowser_mkstemp_path(prefix="lora-probe-klein-src-", suffix=".png")
    out_path = prowser_mkstemp_path(prefix="lora-probe-klein-out-", suffix=".png")
    try:
        Image.new("RGB", (w, h), (100, 120, 140)).save(img_path)
        try:
            os.unlink(out_path)
        except OSError:
            pass
        image = generate_flux2_klein_edit(
            model_name=hf_model_id,
            quantize=4,
            lora_paths=[lora_path],
            lora_scales=[lora_scale],
            prompt=prompt,
            seed=42,
            steps=2,
            width=w,
            height=h,
            guidance=1.0,
            image_paths=[img_path],
            low_ram=True,
            stepwise_dir=None,
        )
        image.save(path=out_path)
        return os.path.isfile(out_path) and os.path.getsize(out_path) >= 64
    except Exception as e:
        if is_lora_incompatibility_error(e):
            return False
        raise
    finally:
        for p in (img_path, out_path):
            try:
                if os.path.isfile(p):
                    os.unlink(p)
            except OSError:
                pass


def probe_lora_on_model(
    model_key: str,
    lora_path: str,
    lora_scale: float,
    cancel_check: Callable[[], bool],
    *,
    entry: Optional[FluxLoraEntry] = None,
) -> bool:
    """Return True if a minimal generation succeeds with this LoRA on model_key."""

    def prompt(fallback: str) -> str:
        if entry is None:
            return fallback
        return lora_probe_prompt(entry, fallback=fallback)

    if model_key == FLUX1_SCHNELL:
        return _probe_t2i(
            hf_model=FLUX1_SCHNELL,
            lora_path=lora_path,
            lora_scale=lora_scale,
            cancel_check=cancel_check,
            prompt=prompt("test"),
        )
    if model_key == FLUX1_DEV:
        return _probe_t2i(
            hf_model=FLUX1_DEV,
            lora_path=lora_path,
            lora_scale=lora_scale,
            cancel_check=cancel_check,
            prompt=prompt("test"),
        )
    if model_key == FLUX1_FILL_DEV:
        return _probe_fill(
            lora_path=lora_path,
            lora_scale=lora_scale,
            cancel_check=cancel_check,
            prompt=prompt("test"),
        )
    if model_key == FLUX2_KLEIN_4B:
        return _probe_klein_edit(
            hf_model_id=FLUX2_KLEIN_4B,
            lora_path=lora_path,
            lora_scale=lora_scale,
            cancel_check=cancel_check,
            prompt=prompt("test edit"),
        )
    if model_key == FLUX2_KLEIN_9B:
        return _probe_klein_edit(
            hf_model_id=FLUX2_KLEIN_9B,
            lora_path=lora_path,
            lora_scale=lora_scale,
            cancel_check=cancel_check,
            prompt=prompt("test edit"),
        )
    if model_key == FLUX2_KLEIN_9B_KV:
        return _probe_klein_edit(
            hf_model_id=FLUX2_KLEIN_9B_KV,
            lora_path=lora_path,
            lora_scale=lora_scale,
            cancel_check=cancel_check,
            prompt=prompt("test edit"),
        )
    raise ValueError(f"Unknown LoRA probe model: {model_key}")


def run_lora_compatibility_check(
    settings: Optional[Dict[str, Any]],
    *,
    progress_callback: Callable[
        [int, int, str, str, str, LoraCheckStats],
        None,
    ],
    cancel_check: Callable[[], bool],
) -> LoraCheckResult:
    """
    Test visible catalog LoRAs per model family.
    progress_callback(probe_index, probe_total, phase, lora_id, model_key, stats)
    phase is 'download' | 'probe'.
    """
    from imagegen_plugins.mflux_lora_presets import resolve_lora_path

    result = LoraCheckResult()
    stats = result.stats
    model_support: Dict[str, List[str]] = {}
    hidden_by_host: Dict[str, List[str]] = {}
    probe_idx = 0
    previous_support = lora_model_support(settings)

    all_entries: List[Tuple[str, FluxLoraEntry]] = []
    for host in lora_hosts_for_settings():
        for entry in catalog_entries_for_settings(settings, host.host_id):
            all_entries.append((host.host_id, entry))

    stats.loras_total = len(all_entries)
    stats.probes_total = count_local_lora_probes([e for _, e in all_entries])

    for host_id, entry in all_entries:
        if cancel_check():
            result.cancelled = True
            break
        lora_id = entry.lora_id
        models = probe_models_for_lora_entry(entry)
        if not models:
            stats.skipped_loras += 1
            continue

        prev_models = set(previous_support.get(lora_id, ()))
        local_models = [m for m in models if lora_probe_model_is_local(m)]
        missing_models = [m for m in models if not lora_probe_model_is_local(m)]
        supported: List[str] = [
            m for m in missing_models if m in prev_models
        ]

        for model_key in missing_models:
            stats.skipped_model_probes += 1
            print(
                f"[Check LoRAs] skipping missing base model {model_key!r} "
                f"for {lora_id!r} (preserving prior compatibility if any)"
            )

        if not local_models:
            model_support[lora_id] = supported
            required = probe_models_for_lora_entry(entry)
            if entry.host_id == HOST_FLUX2_KLEIN:
                passed = bool(required) and all(m in supported for m in required)
            else:
                passed = bool(supported)
            if passed:
                stats.supported_loras += 1
            else:
                stats.removed_loras += 1
            continue

        progress_callback(
            probe_idx,
            stats.probes_total,
            "download",
            lora_id,
            "",
            stats,
        )
        try:
            lora_path = resolve_lora_path(lora_id)
        except Exception:
            stats.skipped_loras += 1
            if supported:
                model_support[lora_id] = supported
            continue

        for model_key in local_models:
            if cancel_check():
                result.cancelled = True
                break
            progress_callback(
                probe_idx,
                stats.probes_total,
                "probe",
                lora_id,
                model_key,
                stats,
            )
            try:
                ok = probe_lora_on_model(
                    model_key,
                    lora_path,
                    entry.scale,
                    cancel_check,
                    entry=entry,
                )
            except Exception:
                ok = False
            if ok and model_key not in supported:
                supported.append(model_key)
            probe_idx += 1
            stats.probes_done = probe_idx
            time.sleep(0)

        if result.cancelled:
            break

        model_support[lora_id] = supported
        required = probe_models_for_lora_entry(entry)
        if entry.host_id == HOST_FLUX2_KLEIN:
            passed = bool(required) and all(m in supported for m in required)
        else:
            # FLUX.1: keep if any listed base model accepts the LoRA.
            passed = bool(supported)
        if passed:
            stats.supported_loras += 1
        else:
            stats.removed_loras += 1

    result.model_support = model_support
    result.hidden_by_host = hidden_by_host
    result.stats = stats
    return result
