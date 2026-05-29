#!/usr/bin/env python3
"""Static FLUX LoRA catalog (curated at dev time; not fetched at runtime)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, FrozenSet, List, Optional, Tuple

PAPER_CUTOUT_LORA_PATH = (
    Path.home()
    / ".cache"
    / "mflux_loras"
    / "paper-cutout"
    / "Flux_1_Dev_LoRA_Paper-Cutout-Style.safetensors"
)

DEFAULT_CACHE = Path.home() / ".cache" / "image_browser" / "mflux_loras"
_ALT_CACHE = Path.home() / ".cache" / "mflux_loras"

MFLUX_LORA_GENERATE_PIPELINES: Tuple[str, ...] = ("flux_schnell_mflux_play",)
MFLUX_LORA_FILL_PIPELINES: Tuple[str, ...] = ("mflux_fill_expand", "mflux_fill_infill")
MFLUX_LORA_T2I_AND_FILL: Tuple[str, ...] = (
    MFLUX_LORA_GENERATE_PIPELINES + MFLUX_LORA_FILL_PIPELINES
)

# FLUX base models probed by Tools > Debug > Check LoRAs (settings key -> UI abbrev).
LORA_PROBE_MODEL_ORDER: Tuple[str, ...] = ("schnell", "dev", "fill")
LORA_MODEL_ABBREV: Dict[str, str] = {
    "schnell": "Schnell",
    "dev": "Dev",
    "fill": "Fill",
}

DEFAULT_ENABLED_LORA_IDS: Tuple[str, ...] = (
    "mspaint1",
    "super_realism",
    "sldr_nsfw_v2",
    "pola_photo_flux",
    "paper_cutout",
)

# Minimum steps when a dev LoRA is active on text-to-image (UI slider + run payload).
LORA_MIN_STEPS = 2


@dataclass(frozen=True)
class FluxLoraEntry:
    lora_id: str
    display_name: str
    repo_id: str = ""
    filename: str = ""
    scale: float = 1.0
    local_path: Optional[str] = None
    mflux_model: str = "dev"
    min_steps: int = LORA_MIN_STEPS
    base_models: Tuple[str, ...] = ("dev",)
    pipelines: Tuple[str, ...] = MFLUX_LORA_T2I_AND_FILL
    # True = verified MFLUX; False = known incompatible; None = untested HF entry.
    mflux_compatible: Optional[bool] = None


def _entry(
    lora_id: str,
    display_name: str,
    repo_id: str,
    filename: str,
    *,
    mflux_compatible: Optional[bool] = None,
    local_path: Optional[str] = None,
    scale: float = 1.0,
    min_steps: int = LORA_MIN_STEPS,
    base_models: Tuple[str, ...] = ("dev",),
    pipelines: Tuple[str, ...] = MFLUX_LORA_T2I_AND_FILL,
) -> FluxLoraEntry:
    return FluxLoraEntry(
        lora_id=lora_id,
        display_name=display_name,
        repo_id=repo_id,
        filename=filename,
        scale=scale,
        local_path=local_path,
        mflux_model="dev",
        min_steps=min_steps,
        base_models=base_models,
        pipelines=pipelines,
        mflux_compatible=mflux_compatible,
    )


FLUX_LORA_CATALOG: Dict[str, FluxLoraEntry] = {
    "mspaint1": _entry(
        "mspaint1",
        "MS Paint style",
        "glif-loradex-trainer/fabian3000_mspaint1",
        "mspaint1.safetensors",
        mflux_compatible=True,
    ),
    "super_realism": _entry(
        "super_realism",
        "Realism (arch)",
        "mnml-ai/flux-arch-realism-lora",
        "flux-arch-realism-lora_v1.safetensors",
        mflux_compatible=True,
    ),
    "sldr_nsfw_v2": _entry(
        "sldr_nsfw_v2",
        "SLDR NSFW v2 (studio)",
        "aifeifei798/sldr_flux_nsfw_v2-studio",
        "sldr_flux_nsfw_v2-studio.safetensors",
        mflux_compatible=True,
    ),
    "pola_photo_flux": _entry(
        "pola_photo_flux",
        "Pola photo",
        "alvdansen/pola-photo-flux",
        "pola_photo_araminta_k.safetensors",
        mflux_compatible=True,
    ),
    "paper_cutout": FluxLoraEntry(
        lora_id="paper_cutout",
        display_name="Paper cutout (local)",
        local_path=str(PAPER_CUTOUT_LORA_PATH),
        scale=1.0,
        mflux_model="dev",
        base_models=("dev",),
        pipelines=MFLUX_LORA_T2I_AND_FILL,
        mflux_compatible=True,
    ),
    "flux_uncensored": _entry(
        "flux_uncensored",
        "Flux uncensored",
        "kenerateai/Flux-uncensored",
        "lora.safetensors",
    ),
    "ms_paint_drawing": _entry(
        "ms_paint_drawing",
        "MS Paint drawing",
        "multimodalart/ms-paint-drawing-flux",
        "ms_paint_flux_lora_aitoolkit_000003000.safetensors",
    ),
    "pixar_3d": _entry(
        "pixar_3d",
        "Pixar 3D",
        "prithivMLmods/Canopus-Pixar-3D-Flux-LoRA",
        "Canopus-Pixar-3D-FluxDev-LoRA.safetensors",
    ),
    "sadie_sink": _entry(
        "sadie_sink",
        "Sadie Sink",
        "playboy40k/flux-SadieSinkLora",
        "sadie-sink.safetensors",
    ),
    "minimal_futuristic": _entry(
        "minimal_futuristic",
        "Minimal futuristic",
        "prithivMLmods/Minimal-Futuristic-Flux-LoRA",
        "Minimal-Futuristic.safetensors",
    ),
    "engrave": _entry(
        "engrave",
        "Engrave",
        "gokaygokay/Flux-Engrave-LoRA",
        "engrave.safetensors",
    ),
    "ghibli": _entry(
        "ghibli",
        "Ghibli",
        "InstantX/FLUX.1-dev-LoRA-Ghibli",
        "ghibli_style.safetensors",
    ),
    "makoto_shinkai": _entry(
        "makoto_shinkai",
        "Makoto Shinkai",
        "InstantX/FLUX.1-dev-LoRA-Makoto-Shinkai",
        "Makoto_Shinkai_style.safetensors",
    ),
    "retro_anime": _entry(
        "retro_anime",
        "Retro anime",
        "Muapi/retro-anime-flux-style",
        "retro-anime-flux-style.safetensors",
    ),
    "sailor_moon_anime": _entry(
        "sailor_moon_anime",
        "Sailor moon anime",
        "Muapi/sailor-moon-esque-retro-anime-style-lora-flux",
        "sailor-moon-esque-retro-anime-style-lora-flux.safetensors",
    ),
    "dnd_covers": _entry(
        "dnd_covers",
        "D&D covers",
        "Muapi/dungeons-and-dragons-covers-dnd-5e",
        "dungeons-and-dragons-covers-dnd-5e.safetensors",
    ),
    "art_deco": _entry(
        "art_deco",
        "Art deco",
        "Muapi/art-deco-style-flux1.d",
        "art-deco-style-flux1.d.safetensors",
    ),
    "klimt": _entry(
        "klimt",
        "Klimt ornamental",
        "Mari-ano/Gustav-Klimt-Ornamental-Symbolist-Aesthetic",
        "gustklim.safetensors",
    ),
    "midsummer_blues": _entry(
        "midsummer_blues",
        "Midsummer blues",
        "Muapi/flux-midsummer-blues",
        "flux-midsummer-blues.safetensors",
    ),
    "microworld_nft": _entry(
        "microworld_nft",
        "Microworld NFT",
        "strangerzonehf/Flux-Microworld-NFT-LoRA",
        "Microworld-NFT.safetensors",
    ),
    "big_boobs_clothed": _entry(
        "big_boobs_clothed",
        "Big boobs clothed",
        "DavidBaloches/Big_Boobs_Clothed",
        "big-boobs-clothed-v2.safetensors",
    ),
    "big_boobs_clothed_v2": _entry(
        "big_boobs_clothed_v2",
        "Big boobs clothed (v2)",
        "aifeifei798/big-boobs-clothed",
        "big-boobs-clothed-v2.safetensors",
    ),
    "sideboob": _entry(
        "sideboob",
        "Sideboob",
        "Genner2025/sideboob",
        "Candid_Armhole_Sideboob_Nipslip-000003.safetensors",
    ),
    "fluxpony": _entry(
        "fluxpony",
        "Fluxpony",
        "uriel353/fluxpony-perfect-full-round-breasts-and-slim-waist_V3_R128",
        "fluxpony-perfect-full-round-breasts-and-slim-waist.safetensors",
    ),
    "pizzacake_art": _entry(
        "pizzacake_art",
        "Pizzacake art style",
        "Muapi/pizzacake-ellen-woodbury-art-style-flux-illustrious-pony",
        "pizzacake-ellen-woodbury-art-style-flux-illustrious-pony.safetensors",
    ),
    "omnipaint": _entry(
        "omnipaint",
        "OmniPaint",
        "yeates/OmniPaint",
        "weights/omnipaint_insert.safetensors",
        pipelines=MFLUX_LORA_FILL_PIPELINES,
        base_models=("dev", "fill"),
    ),
    "feifei_v1": _entry(
        "feifei_v1",
        "Feifei v1",
        "aifeifei798/feifei-flux-lora-v1",
        "mj.safetensors",
    ),
    "sarah_mcdaniel": _entry(
        "sarah_mcdaniel",
        "Sarah McDaniel",
        "Keltezaa/SarahMcDaniel",
        "SarahMcDaniel_rank16_bf16-step00750.safetensors",
    ),
    "ms_paint_alt": _entry(
        "ms_paint_alt",
        "MS Paint drawing (alt)",
        "multimodalart/ms-paint-drawing-flux",
        "ms_paint_flux_lora_aitoolkit_000003000.safetensors",
    ),
}


def catalog_entries_sorted() -> Tuple[FluxLoraEntry, ...]:
    return tuple(sorted(FLUX_LORA_CATALOG.values(), key=lambda e: e.display_name.lower()))


def lora_model_support(settings: Optional[Dict[str, Any]] = None) -> Dict[str, Tuple[str, ...]]:
    """Per-LoRA supported probe models from settings (empty tuple = tested, none work)."""
    if settings is None:
        from config import get_config

        settings = get_config().load_settings()
    imagegen = settings.get("imagegen") or {}
    lc = imagegen.get("lora_catalog") or {}
    raw = lc.get("model_support")
    if not isinstance(raw, dict):
        return {}
    out: Dict[str, Tuple[str, ...]] = {}
    for lid, models in raw.items():
        lid_s = str(lid)
        if lid_s not in FLUX_LORA_CATALOG:
            continue
        if not isinstance(models, list):
            continue
        supported = tuple(
            m for m in LORA_PROBE_MODEL_ORDER if str(m) in {str(x) for x in models}
        )
        out[lid_s] = supported
    return out


def format_lora_model_support_suffix(supported_models: Tuple[str, ...]) -> str:
    """Parenthetical shorthand for Settings / menus, e.g. ' (Schnell, Dev, Fill)'."""
    if not supported_models:
        return ""
    labels = [
        LORA_MODEL_ABBREV[m]
        for m in LORA_PROBE_MODEL_ORDER
        if m in supported_models
    ]
    if not labels:
        return ""
    return f" ({', '.join(labels)})"


def lora_settings_display_name(
    entry: FluxLoraEntry,
    settings: Optional[Dict[str, Any]] = None,
) -> str:
    """Display name with optional model-support suffix from settings."""
    support = lora_model_support(settings).get(entry.lora_id)
    if support is None:
        return entry.display_name
    return entry.display_name + format_lora_model_support_suffix(support)


def probe_models_for_lora_entry(entry: FluxLoraEntry) -> Tuple[str, ...]:
    """Which FLUX LoRA-capable base models to test for this catalog entry."""
    models: List[str] = []
    t2i = any(p in MFLUX_LORA_GENERATE_PIPELINES for p in entry.pipelines)
    fill = any(p in MFLUX_LORA_FILL_PIPELINES for p in entry.pipelines)
    if t2i and (
        "schnell" in entry.base_models
        or "dev" in entry.base_models
    ):
        models.append("schnell")
    if t2i and "dev" in entry.base_models:
        models.append("dev")
    if fill and (
        "fill" in entry.base_models
        or "dev" in entry.base_models
    ):
        models.append("fill")
    # Dedupe while preserving order.
    seen: set = set()
    ordered: List[str] = []
    for m in models:
        if m not in seen:
            seen.add(m)
            ordered.append(m)
    return tuple(ordered)


def deleted_lora_ids(settings: Optional[Dict[str, Any]] = None) -> FrozenSet[str]:
    """LoRA ids hidden from Settings list and Create dropdowns (re-enable via settings.json)."""
    if settings is None:
        from config import get_config

        settings = get_config().load_settings()
    imagegen = settings.get("imagegen") or {}
    lc = imagegen.get("lora_catalog") or {}
    raw = lc.get("deleted_ids")
    if not isinstance(raw, list):
        return frozenset()
    return frozenset(str(x) for x in raw if str(x) in FLUX_LORA_CATALOG)


def catalog_entries_for_settings(
    settings: Optional[Dict[str, Any]] = None,
) -> Tuple[FluxLoraEntry, ...]:
    hidden = deleted_lora_ids(settings)
    return tuple(
        e
        for e in catalog_entries_sorted()
        if e.mflux_compatible is not False and e.lora_id not in hidden
    )


def get_lora_entry(lora_id: str) -> Optional[FluxLoraEntry]:
    return FLUX_LORA_CATALOG.get(lora_id)


def catalog_cache_path(entry: FluxLoraEntry) -> Optional[Path]:
    if entry.local_path:
        return Path(entry.local_path).expanduser()
    if not entry.repo_id or not entry.filename:
        return None
    return DEFAULT_CACHE / entry.repo_id.replace("/", "__") / entry.filename


def is_lora_installed(lora_id: str) -> bool:
    entry = FLUX_LORA_CATALOG.get(lora_id)
    if entry is None:
        return False
    path = catalog_cache_path(entry)
    if path is None:
        return False
    if path.is_file() and path.stat().st_size > 1024:
        return True
    if entry.local_path:
        alt = _ALT_CACHE / "paper-cutout" / path.name
        if alt.is_file() and alt.stat().st_size > 1024:
            return True
    return False


def installed_lora_ids() -> FrozenSet[str]:
    return frozenset(lid for lid in FLUX_LORA_CATALOG if is_lora_installed(lid))


def enabled_lora_ids(settings: Optional[Dict[str, Any]] = None) -> Tuple[str, ...]:
    if settings is None:
        from config import get_config

        settings = get_config().load_settings()
    imagegen = settings.get("imagegen") or {}
    lc = imagegen.get("lora_catalog") or {}
    hidden = deleted_lora_ids(settings)
    raw = lc.get("enabled_ids")
    if isinstance(raw, list):
        return tuple(
            str(x) for x in raw if str(x) in FLUX_LORA_CATALOG and str(x) not in hidden
        )
    return tuple(x for x in DEFAULT_ENABLED_LORA_IDS if x not in hidden)


def resolve_plugin_base_model(hf_model_id: str, pipeline_id: str) -> str:
    hf = (hf_model_id or "").strip().lower()
    if pipeline_id in MFLUX_LORA_FILL_PIPELINES or "fill" in hf:
        return "fill"
    if hf in ("schnell",):
        return "schnell"
    if hf in ("dev",):
        return "dev"
    return "dev"


def entry_matches_base(entry: FluxLoraEntry, plugin_base: str) -> bool:
    if plugin_base in entry.base_models:
        return True
    if plugin_base == "schnell" and "dev" in entry.base_models:
        return True
    if plugin_base == "fill" and "dev" in entry.base_models:
        return True
    return False


def lora_visible_in_dropdown(
    lora_id: str,
    entry: FluxLoraEntry,
    *,
    enabled: FrozenSet[str],
    deleted: FrozenSet[str],
) -> bool:
    """True when LoRA is visible on Settings → LoRA (not deleted) and checked."""
    if lora_id in deleted:
        return False
    if entry.mflux_compatible is False:
        return False
    return lora_id in enabled


def lora_choices_for_pipeline(
    pipeline_id: str,
    plugin_hf_model_id: str,
    settings: Optional[Dict[str, Any]] = None,
) -> Tuple[Tuple[str, str], ...]:
    enabled = frozenset(enabled_lora_ids(settings))
    deleted = deleted_lora_ids(settings)
    plugin_base = resolve_plugin_base_model(plugin_hf_model_id, pipeline_id)
    choices: List[Tuple[str, str]] = [("None", "none")]
    for entry in catalog_entries_sorted():
        if pipeline_id not in entry.pipelines:
            continue
        if not entry_matches_base(entry, plugin_base):
            continue
        if not lora_visible_in_dropdown(
            entry.lora_id,
            entry,
            enabled=enabled,
            deleted=deleted,
        ):
            continue
        choices.append((entry.display_name, entry.lora_id))
    return tuple(choices)


def lora_entry_min_steps(lora_id: str) -> Optional[int]:
    entry = FLUX_LORA_CATALOG.get(lora_id)
    return entry.min_steps if entry is not None else None


def manual_download_help(lora_id: str) -> str:
    entry = FLUX_LORA_CATALOG.get(lora_id)
    if entry is None:
        return "Unknown LoRA."
    if entry.local_path:
        return f"Local LoRA ({lora_id}): {entry.local_path}"
    dest = catalog_cache_path(entry)
    if dest is None:
        return "Unknown LoRA."
    return (
        f"Manual download ({lora_id}):\n"
        f"  URL: https://huggingface.co/{entry.repo_id}/resolve/main/{entry.filename}\n"
        f"  Save to: {dest}\n"
        f"Or: hf download {entry.repo_id} {entry.filename} --local-dir {dest.parent}"
    )


def sample_flux_lora_download_entries() -> Tuple[FluxLoraEntry, ...]:
    """MFLUX-verified HF LoRAs used as the default sample download set."""
    return tuple(
        e
        for e in catalog_entries_sorted()
        if e.mflux_compatible is True and e.repo_id and e.filename
    )


def _lora_download_local_dir(entry: FluxLoraEntry) -> Path:
    return DEFAULT_CACHE / entry.repo_id.replace("/", "__")
