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
    REALISTIC_VISION_V4_NOVAE,
    SCENEWORKS_FLUX2_KLEIN_9B_KV_MLX,
    SD15_DEFAULT_VAE,
    SD15_LORA_MODEL_KEYS,
    SDXL_BASE_1_0,
    lora_model_display_name,
)
from imagegen_plugins.lora_catalog import (
    FluxLoraEntry,
    catalog_entries_sorted,
    local_lora_weights_path,
    lora_choice_label,
    lora_model_support,
    lora_probe_prompt,
    probe_models_for_lora_entry,
)
from imagegen_plugins.lora_catalog_settings import model_state
from imagegen_plugins.lora_host_registry import HOST_SD15, HOST_SDXL

_DIFFUSERS_LORA_HOSTS = frozenset({HOST_SD15, HOST_SDXL})
from imagegen_plugins.lora_model_registry import lora_probe_model_is_local

# Models probe_lora_on_model can exercise.
_PROBEABLE_MODEL_KEYS = frozenset(
    {
        FLUX1_SCHNELL,
        FLUX1_DEV,
        FLUX1_FILL_DEV,
        FLUX2_KLEIN_4B,
        FLUX2_KLEIN_9B,
        FLUX2_KLEIN_9B_KV,
        SCENEWORKS_FLUX2_KLEIN_9B_KV_MLX,
        SDXL_BASE_1_0,
        *SD15_LORA_MODEL_KEYS,
    }
)


@dataclass
class LoraCheckStats:
    loras_total: int = 0
    loras_done: int = 0
    lora_index: int = 0  # 1-based current LoRA among those being probed
    models_total: int = 0  # unique installed probeable models in plan
    models_for_lora: int = 0
    model_index_for_lora: int = 0  # 1-based within current LoRA
    probes_done: int = 0
    probes_total: int = 0
    probe_current: int = 0  # 1-based in-flight / just-finished probe
    supported_loras: int = 0
    removed_loras: int = 0
    skipped_loras: int = 0
    skipped_not_on_disk: int = 0
    skipped_model_probes: int = 0
    newly_enabled_count: int = 0
    newly_supported_count: int = 0
    failed_probe_count: int = 0
    skipped_hidden_count: int = 0
    last_result: str = ""  # pass | fail | skip | ""


@dataclass
class LoraCheckChange:
    kind: str  # newly_supported | lost_support | newly_enabled | skipped_hidden | failed | skipped_not_on_disk
    lora_id: str
    lora_label: str
    model_key: str = ""
    model_label: str = ""


@dataclass
class LoraCheckResult:
    model_support: Dict[str, List[str]] = field(default_factory=dict)
    by_model: Dict[str, Dict[str, List[str]]] = field(default_factory=dict)
    changes: List[LoraCheckChange] = field(default_factory=list)
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


def _probeable_local_models(entry: FluxLoraEntry) -> List[str]:
    return [
        m
        for m in probe_models_for_lora_entry(entry)
        if m in _PROBEABLE_MODEL_KEYS and lora_probe_model_is_local(m)
    ]


def count_local_lora_probes(entries: List[FluxLoraEntry]) -> int:
    """Probe count for progress UI (installed, probeable base models only)."""
    return sum(len(_probeable_local_models(e)) for e in entries)


def plan_disk_lora_probes(
    settings: Optional[Dict[str, Any]],
) -> Tuple[List[FluxLoraEntry], List[Tuple[FluxLoraEntry, List[str]]], LoraCheckStats]:
    """
    Catalog entries with on-disk weights and at least one local probeable model.
    Returns (all_catalog_candidates, probe_plan, initial_stats).
    """
    stats = LoraCheckStats()
    candidates: List[FluxLoraEntry] = []
    for entry in catalog_entries_sorted(settings):
        if entry.mflux_compatible is False:
            continue
        if entry.host_id in _DIFFUSERS_LORA_HOSTS:
            continue
        candidates.append(entry)

    plan: List[Tuple[FluxLoraEntry, List[str]]] = []
    models_seen: set[str] = set()
    for entry in candidates:
        path = local_lora_weights_path(entry.lora_id, settings)
        if path is None:
            stats.skipped_not_on_disk += 1
            continue
        local_models = _probeable_local_models(entry)
        family = [
            m
            for m in probe_models_for_lora_entry(entry)
            if m in _PROBEABLE_MODEL_KEYS
        ]
        missing = [m for m in family if not lora_probe_model_is_local(m)]
        stats.skipped_model_probes += len(missing)
        if not local_models:
            stats.skipped_loras += 1
            continue
        plan.append((entry, local_models))
        models_seen.update(local_models)

    stats.loras_total = len(plan)
    stats.models_total = len(models_seen)
    stats.probes_total = sum(len(models) for _, models in plan)
    return candidates, plan, stats


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
    quantize: int | None = 4,
    model_path: str | None = None,
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
            quantize=quantize,
            model_path=model_path,
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


def _probe_diffusers(
    *,
    pipeline: str,
    hf_model_id: str,
    lora_path: str,
    lora_scale: float,
    cancel_check: Callable[[], bool],
    vae_hf_model_id: str = "",
) -> bool:
    """Load diffusers SD 1.5 / SDXL pipeline + LoRA weights (no inference)."""
    if cancel_check():
        return False
    try:
        if pipeline == "sd15":
            from imagegen_plugins.pipelines.sd15_diffusers import probe_lora_weights

            probe_lora_weights(
                hf_model_id,
                lora_path,
                lora_scale,
                vae_hf_model_id=vae_hf_model_id,
            )
        elif pipeline == "sdxl":
            from imagegen_plugins.pipelines.sdxl_diffusers import probe_lora_weights

            probe_lora_weights(hf_model_id, lora_path, lora_scale)
        else:
            raise ValueError(f"Unknown diffusers probe pipeline: {pipeline}")
        return True
    except Exception as e:
        if is_lora_incompatibility_error(e):
            return False
        msg = f"{type(e).__name__}: {e}".lower()
        if "lora" in msg or "peft" in msg or "adapter" in msg:
            return False
        raise
    finally:
        try:
            if pipeline == "sd15":
                from imagegen_plugins.pipelines.sd15_diffusers import unload_pipeline

                unload_pipeline()
            elif pipeline == "sdxl":
                from imagegen_plugins.pipelines.sdxl_diffusers import unload_pipeline

                unload_pipeline()
        except Exception:
            pass


def probe_lora_on_model(
    model_key: str,
    lora_path: str,
    lora_scale: float,
    cancel_check: Callable[[], bool],
    *,
    entry: Optional[FluxLoraEntry] = None,
) -> bool:
    """Return True if a minimal probe succeeds with this LoRA on model_key."""

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
    if model_key == SCENEWORKS_FLUX2_KLEIN_9B_KV_MLX:
        from imagegen_plugins.sceneworks_klein_mlx import (
            DEFAULT_MLX_TIER,
            resolve_tier_model_path,
        )

        tier_path = resolve_tier_model_path(
            SCENEWORKS_FLUX2_KLEIN_9B_KV_MLX,
            DEFAULT_MLX_TIER,
        )
        if not tier_path:
            return False
        return _probe_klein_edit(
            hf_model_id=SCENEWORKS_FLUX2_KLEIN_9B_KV_MLX,
            lora_path=lora_path,
            lora_scale=lora_scale,
            cancel_check=cancel_check,
            prompt=prompt("test edit"),
            quantize=None,
            model_path=tier_path,
        )
    if model_key in SD15_LORA_MODEL_KEYS:
        vae = (
            SD15_DEFAULT_VAE
            if model_key == REALISTIC_VISION_V4_NOVAE
            else ""
        )
        return _probe_diffusers(
            pipeline="sd15",
            hf_model_id=model_key,
            lora_path=lora_path,
            lora_scale=lora_scale,
            cancel_check=cancel_check,
            vae_hf_model_id=vae,
        )
    if model_key == SDXL_BASE_1_0:
        return _probe_diffusers(
            pipeline="sdxl",
            hf_model_id=SDXL_BASE_1_0,
            lora_path=lora_path,
            lora_scale=lora_scale,
            cancel_check=cancel_check,
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
    Probe on-disk catalog LoRAs against installed models in each LoRA's family.
    Does not download missing weights. Enables passers (unless hidden).
    progress_callback(probe_index, probe_total, phase, lora_id, model_key, stats)
    phase is 'scan' | 'probe'.
    """
    result = LoraCheckResult()
    previous_support = lora_model_support(settings)
    model_support: Dict[str, List[str]] = {}
    # Accumulated enables per model (start from current settings; merge new).
    by_model_enabled: Dict[str, List[str]] = {}
    by_model_hidden: Dict[str, List[str]] = {}

    progress_callback(0, 1, "scan", "", "", LoraCheckStats())
    _candidates, plan, stats = plan_disk_lora_probes(settings)
    result.stats = stats

    for entry, _models in plan:
        for model_key in _models:
            if model_key not in by_model_enabled:
                st = model_state(settings, model_key)
                by_model_enabled[model_key] = list(st.get("enabled_ids") or [])
                by_model_hidden[model_key] = list(
                    st.get("deleted_ids") or st.get("hidden_ids") or []
                )

    for lid, skipped_entry in (
        (e.lora_id, e)
        for e in _candidates
        if local_lora_weights_path(e.lora_id, settings) is None
        and e.host_id not in _DIFFUSERS_LORA_HOSTS
        and e.mflux_compatible is not False
    ):
        result.changes.append(
            LoraCheckChange(
                kind="skipped_not_on_disk",
                lora_id=lid,
                lora_label=lora_choice_label(skipped_entry),
            )
        )

    progress_callback(0, max(1, stats.probes_total), "scan", "", "", stats)
    if not plan:
        result.model_support = model_support
        result.stats = stats
        return result

    probe_idx = 0
    for lora_i, (entry, local_models) in enumerate(plan, start=1):
        if cancel_check():
            result.cancelled = True
            break

        lora_id = entry.lora_id
        lora_label = lora_choice_label(entry)
        path = local_lora_weights_path(lora_id, settings)
        if path is None:
            stats.skipped_loras += 1
            stats.loras_done = lora_i
            continue

        lora_path = str(path)
        prev_models = set(previous_support.get(lora_id, ()))
        family = [
            m
            for m in probe_models_for_lora_entry(entry)
            if m in _PROBEABLE_MODEL_KEYS
        ]
        missing_models = [m for m in family if not lora_probe_model_is_local(m)]
        # Keep prior compatibility for base models not installed this run.
        supported: List[str] = [m for m in missing_models if m in prev_models]

        stats.lora_index = lora_i
        stats.models_for_lora = len(local_models)
        stats.model_index_for_lora = 0
        stats.last_result = ""

        for model_i, model_key in enumerate(local_models, start=1):
            if cancel_check():
                result.cancelled = True
                break

            stats.model_index_for_lora = model_i
            stats.probe_current = probe_idx + 1
            stats.last_result = ""
            progress_callback(
                probe_idx,
                stats.probes_total,
                "probe",
                lora_id,
                model_key,
                stats,
            )
            print(
                f"[Check LoRAs] LoRA {lora_i}/{stats.loras_total} "
                f"«{lora_label}» · model {model_i}/{len(local_models)} "
                f"{lora_model_display_name(model_key)} "
                f"(probe {stats.probe_current}/{stats.probes_total})"
            )
            try:
                ok = probe_lora_on_model(
                    model_key,
                    lora_path,
                    entry.scale,
                    cancel_check,
                    entry=entry,
                )
            except Exception as e:
                print(f"[Check LoRAs] probe error {lora_id!r} on {model_key!r}: {e}")
                ok = False

            model_label = lora_model_display_name(model_key)
            was_supported = model_key in prev_models
            if ok:
                stats.last_result = "pass"
                if model_key not in supported:
                    supported.append(model_key)
                if not was_supported:
                    stats.newly_supported_count += 1
                    result.changes.append(
                        LoraCheckChange(
                            kind="newly_supported",
                            lora_id=lora_id,
                            lora_label=lora_label,
                            model_key=model_key,
                            model_label=model_label,
                        )
                    )
                hidden = set(by_model_hidden.get(model_key, ()))
                enabled = by_model_enabled.setdefault(model_key, [])
                if lora_id in hidden:
                    stats.skipped_hidden_count += 1
                    result.changes.append(
                        LoraCheckChange(
                            kind="skipped_hidden",
                            lora_id=lora_id,
                            lora_label=lora_label,
                            model_key=model_key,
                            model_label=model_label,
                        )
                    )
                elif lora_id not in enabled:
                    enabled.append(lora_id)
                    stats.newly_enabled_count += 1
                    result.changes.append(
                        LoraCheckChange(
                            kind="newly_enabled",
                            lora_id=lora_id,
                            lora_label=lora_label,
                            model_key=model_key,
                            model_label=model_label,
                        )
                    )
            else:
                stats.last_result = "fail"
                stats.failed_probe_count += 1
                result.changes.append(
                    LoraCheckChange(
                        kind="failed",
                        lora_id=lora_id,
                        lora_label=lora_label,
                        model_key=model_key,
                        model_label=model_label,
                    )
                )
                if was_supported:
                    result.changes.append(
                        LoraCheckChange(
                            kind="lost_support",
                            lora_id=lora_id,
                            lora_label=lora_label,
                            model_key=model_key,
                            model_label=model_label,
                        )
                    )

            probe_idx += 1
            stats.probes_done = probe_idx
            progress_callback(
                probe_idx,
                stats.probes_total,
                "probe",
                lora_id,
                model_key,
                stats,
            )
            time.sleep(0)

        if result.cancelled:
            # Persist partial support for probes completed on this LoRA.
            model_support[lora_id] = supported
            break

        model_support[lora_id] = supported
        if supported:
            stats.supported_loras += 1
        else:
            stats.removed_loras += 1
        stats.loras_done = lora_i

    result.model_support = model_support
    result.by_model = {
        mk: {
            "enabled_ids": list(by_model_enabled.get(mk, [])),
            "deleted_ids": list(by_model_hidden.get(mk, [])),
        }
        for mk in by_model_enabled
    }
    result.stats = stats
    return result
